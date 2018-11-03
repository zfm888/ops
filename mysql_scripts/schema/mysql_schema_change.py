#! /usr/bin/python
# -*- coding:utf-8 -*-

import os
import argparse
import getpass
import re
import logging
import subprocess
from distutils import spawn
from datetime import datetime

import MySQLdb

# 功能：
#   依次执行指定目录下的MySQL变更脚本，并记录执行信息
# 注意：
#   1. 依赖MySQL-python(Python3依赖mysqlclient)
#   2. 变更脚本文件名格式为：(数字开头) + (_或-) + (字母、数字、_) + (.sql结尾)，开头的数字作为变更序号
#   3. 每个变更脚本的内容应尽量保持原子性，方便执行错误时回退
#   4. MySQL表结构修改成本很高，对一个表的多处修改应尽量整合为一条SQL
#   5. 序号为0的脚本作为基线，不执行
#   6. 不检查变更脚本的内容，其正确性&危险性由变更脚本的开发人员负责（使用适当授权的用户可以降低风险）

# 定义常量
CREATE = '''CREATE TABLE {database}.{table} (
  change_id int NOT NULL,
  description varchar(200) NULL,
  apply_at datetime NOT NULL,
  complete_at datetime NULL,
  success char(1) NOT NULL,
  PRIMARY KEY (change_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8'''

INSERT = "INSERT INTO {database}.{table} (change_id, description, apply_at, success) values (%s, %s, %s, 'N')"

UPDATE = 'UPDATE {database}.{table} SET complete_at = %s, success = %s WHERE change_id = %s'

NAME_PATTERN = re.compile('^(\d+)[_\-][0-9a-zA-Z_]*\.sql$')

LOGGER = logging.getLogger('apply_schema_change')


# 定义异常
class TableError(Exception):
    def __init__(self, database, table):
        sql = CREATE.format(database=database, table=table)
        msg = "{database}.{table} doesn't exist, please check your spell or create it using:\n{sql}".format(
            database=database,
            table=table,
            sql=sql)
        super(TableError, self).__init__(msg)


class ApplyError(Exception):
    def __init__(self, file_path, message):
        msg = 'error occurred while applying {0}:\n'.format(file_path)
        msg += message
        super(ApplyError, self).__init__(msg)


class StateError(Exception):
    def __init__(self, change_id, description):
        msg = 'change #{0}: {1} previously failed, please fix it manually (undo this change --> ' \
              'execute the correct script --> update change log record)'.format(change_id, description)
        super(StateError, self).__init__(msg)


# 解析参数
def parse_args():
    parser = argparse.ArgumentParser(description='Apply Database Schema Changes')

    default_host = 'localhost'
    parser.add_argument('--host',
                        default=default_host,
                        help='name of host to connect to, default: {0}'.format(default_host))

    default_port = 3306
    parser.add_argument('--port',
                        type=int,
                        default=default_port,
                        help='TCP port, default: {0}'.format(default_port))

    default_socket = '/var/lib/mysql/mysql.sock'
    parser.add_argument('--socket',
                        default=default_socket,
                        help='location of UNIX socket, default: {0}'.format(default_socket))

    default_user = 'root'
    parser.add_argument('--user',
                        default=default_user,
                        help='user to authenticate as, default: {0}'.format(default_user))

    parser.add_argument('--password',
                        default='',
                        help='password to authenticate with, default: no')

    default_table = 'schema_changelog'
    parser.add_argument('--table',
                        default=default_table,
                        help='change log table name, default: {0}'.format(default_table))

    default_last = None
    parser.add_argument('--last',
                        type=int,
                        default=default_last,
                        help='last change id to apply (included), default: None (all changes)')

    parser.add_argument('--debug',
                        action='store_true',
                        help='enable debug')

    parser.add_argument('database',
                        help='database name to apply changes')
    parser.add_argument('directory',
                        help='directory holding change scripts (absolute path)')

    args = parser.parse_args()

    if not os.path.isabs(args.directory):
        raise ValueError('directory should be absolute path')
    if not os.path.exists(args.directory):
        raise ValueError("{0} doesn't exist".format(args.directory))
    if not os.path.isdir(args.directory):
        raise ValueError('{0} is not dir'.format(args.directory))

    if not args.password:
        args.password = getpass.getpass()

    LOGGER.debug('parsed args: {0}'.format(args))
    return args


# 建立数据库连接
def connect(args):
    if args.host == 'localhost' and args.socket:
        conn = MySQLdb.connect(host=args.host, unix_socket=args.socket, user=args.user, passwd=args.password,
                               db=args.database)
    else:
        conn = MySQLdb.connect(host=args.host, port=args.port, user=args.user, passwd=args.password, db=args.database)

    LOGGER.debug('database connection created')
    return conn


# 查询已应用的变更
def applied_changes(conn, args):
    sql = 'SELECT change_id, description, apply_at, complete_at, success FROM {0} ORDER BY change_id DESC'.format(
        args.table)
    LOGGER.debug('select statement: {0}'.format(sql))

    cur = conn.cursor()
    try:
        cur.execute(sql)
        res = cur.fetchall()
        return res
    except Exception:
        raise TableError(args.database, args.table)
    finally:
        cur.close()


# 目录中的变更脚本
def all_changes(args):
    res = {}
    for file in os.listdir(args.directory):
        file_path = os.path.join(args.directory, file)
        if os.path.isfile(file_path):
            change_id = parse_id(file_path)
            LOGGER.debug('change_id: #{0}, file_path: {1}'.format(change_id, file_path))

            if not change_id:
                continue

            if change_id not in res:
                res[change_id] = file_path
            else:
                raise ValueError('change_id {0} duplicate:\n{1}\n{2}'.format(change_id, res[change_id], file_path))

    return res


# 从文件名解析变更ID
def parse_id(file_path):
    base_name = os.path.basename(file_path)
    match = NAME_PATTERN.match(base_name)
    if not match:
        return None
    else:
        return int(match.group(1))


# 可执行文件路径
def binary_path(name):
    path = spawn.find_executable(name)
    if not path:
        raise ValueError("can't find {0}, please check your PATH env variable".format(name))
    else:
        return path


# 执行变更脚本
def apply_change(args, mysql_client, file_path):
    command = [
        mysql_client,
        '--host={0}'.format(args.host),
        '--user={0}'.format(args.user),
        '--password={0}'.format(args.password),
        '--database={0}'.format(args.database)
    ]

    if args.host == 'localhost' and args.socket:
        command.extend([
            '--protocol=SOCKET',
            '--socket={0}'.format(args.socket)
        ])
    else:
        command.extend([
            '--protocol=TCP',
            '--port={0}'.format(args.port)
        ])

    execute = 'source {0}'.format(file_path)

    LOGGER.debug('command: {0} {1}'.format(' '.join([c for c in command if '--password' not in c]), execute))

    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout, stderr = child.communicate(execute)

    LOGGER.debug('stdout: {0}'.format(stdout))
    LOGGER.debug('stderr: {0}'.format(stderr))

    if child.returncode != 0:
        raise ApplyError(file_path, stderr if stderr else stdout)


# 写入变更记录
def record_change(conn, args, change_id, description=None, end=False, success=False):
    if end:
        sql = UPDATE.format(database=args.database, table=args.table)
        sql_args = (datetime.now(), 'Y' if success else 'N', change_id)
    else:
        sql = INSERT.format(database=args.database, table=args.table)
        sql_args = (change_id, description, datetime.now())

    LOGGER.debug('record change statement: {0}'.format(sql))
    LOGGER.debug('record change values: {0}'.format(sql_args))

    cur = conn.cursor()

    try:
        cur.execute(sql, sql_args)
        conn.commit()
    finally:
        cur.close()


# 设置log
def config_log(args):
    level = logging.DEBUG if args.debug else logging.INFO
    LOGGER.setLevel(level)

    formatter = logging.Formatter(fmt='%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y%m%d_%H%M%S')

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    LOGGER.addHandler(console_handler)


if __name__ == '__main__':
    args = parse_args()
    config_log(args)

    mysql_client = binary_path('mysql')  # mysql客户端路径
    conn = connect(args)  # 建立数据库连接

    try:
        applied = applied_changes(conn, args)  # 已执行的变更记录

        max_applied_id = None  # 已执行的最大变更ID
        if applied:
            max_applied_id = applied[0][0]

            for record in applied:
                if record[-1] in ('n', 'N'):  # 如果有失败记录，抛出异常，需先解决遗留问题
                    raise StateError(change_id=record[0], description=record[1])

        all_scripts = all_changes(args)  # 所有变更脚本
        for change_id in sorted(all_scripts.keys()):
            if (change_id >= 1 and  # change_id为0的脚本作为基线，不执行
                    (max_applied_id is None or change_id > max_applied_id) and
                    (args.last is None or change_id <= args.last)):
                LOGGER.info('applying #{0}: {1}'.format(change_id, all_scripts[change_id]))

                record_change(conn, args, change_id, description=os.path.basename(all_scripts[change_id]), end=False)

                try:
                    apply_change(args, mysql_client, all_scripts[change_id])
                    record_change(conn, args, change_id, end=True, success=True)
                except Exception as exc:
                    record_change(conn, args, change_id, end=True, success=False)
                    raise exc
    finally:
        if conn:
            conn.close()

    LOGGER.info('Done!')
