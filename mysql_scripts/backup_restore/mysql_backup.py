# -*- coding:utf-8 -*-

from __future__ import print_function

import logging
from datetime import datetime
from distutils import spawn
import os
import subprocess
import sys


# 功能：
#   1. 使用xtrabackup备份MySQL
#   2. 可选择全量备份、增量备份
#   3. 增量备份时自动确定incremental-basedir
#   4. 增量备份时对全备及其后备份链检查，如果没有全备或者备份链不完整，则自动进行全量备份
#   5. 可选择将备份文件scp至其他服务器
#   6. 可选择备份保留份数
#   7. 可返回备份执行情况供zabbix监控使用
# 注意：
#   1. 需安装xtrabackup
#   2. ssh/scp需要配置无密钥访问
# TODO:
#   1. Binlog备份
#   2. FTP传输

# ==================配置信息==================

# 备份目标目录
TARGET_PATH = '/data/mysqlbackup'

# MySQL配置文件
MYSQL_CNF = '/usr/local/mysql/my.cnf'

# MySQL用户
MYSQL_USER = 'root'

# MySQL密码
MYSQL_PASSWORD = 'password'

# xtrabackup文件
# 默认从PATH中查找，可手动设置绝对路径
XTRABACKUP = spawn.find_executable('xtrabackup')

# 是否将备份复制到远端
# 可选：off, scp
# 注意：使用SCP需要配置无密钥访问
COPY_TO_REMOTE = 'off'

REMOTE_HOST = '192.168.56.1'

REMOTE_USER = 'mysql'

REMOTE_PATH = '/data/mysql_hostname'

# 备份保留份数
BACKUP_REDUNDANCY = 1

# ==================功能实现==================
DATEFMT = '%Y%m%d_%H%M%S'

# index文件每行字段为backup_dir event_name occur_time
# event_name取值包括backup_begin/backup_end/backup_error/copy_begin/copy_end/copy_error
index_file = os.path.join(TARGET_PATH, 'mysql_backup.index')
log_file = os.path.join(TARGET_PATH, 'mysql_backup.log')
output_file = os.path.join(TARGET_PATH, 'xtrabackup_output.log')

# log
logger = logging.getLogger('mysql_backup')
logger.setLevel(logging.INFO)
formatter = logging.Formatter(
    fmt='%(asctime)s [%(levelname)s] %(message)s',
    datefmt=DATEFMT
)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


# 异常定义
class ProgramError(Exception):
    def __init__(self, message):
        super(ProgramError, self).__init__(message)


class ProcessError(Exception):
    def __init__(self, command, returncode):
        message = 'Command Failed: {0}, Return code: {1}'.format(command, returncode)
        super(ProcessError, self).__init__(message)
        self.command = command
        self.returncode = returncode


# 日志设置
def setup_log():
    try:
        file_handler = logging.FileHandler(
            filename=log_file,
            mode='a')
    except Exception as exc:
        logger.error(str(exc))
        raise exc

    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


# 检查配置
def check_conf():
    if XTRABACKUP is None or (not os.path.exists(XTRABACKUP)):
        msg = 'Cannot find xtrabackup: {0}'.format(XTRABACKUP)
        logger.error(msg)
        raise ProgramError(msg)

    if MYSQL_CNF is None or (not os.path.exists(MYSQL_CNF)) or (not os.path.isfile(MYSQL_CNF)):
        msg = 'Cannot find MySQL conf file: {0}'.format(MYSQL_CNF)
        logger.error(msg)
        raise ProgramError(msg)

    if TARGET_PATH is None or (not os.path.exists(TARGET_PATH)) or (not os.path.isdir(TARGET_PATH)):
        msg = 'Cannot find backup target path: {0}'.format(TARGET_PATH)
        logger.error(msg)
        raise ProgramError(msg)

    if BACKUP_REDUNDANCY is None or BACKUP_REDUNDANCY <= 0:
        msg = 'Backup Redundancy: {0}, will not remove old backups'.format(BACKUP_REDUNDANCY)
        logger.warning(msg)

    if len(sys.argv) < 2 or sys.argv[1].lower() not in ('full', 'incr', 'monitor'):
        msg = 'Wrong argument: {0}. Usage：{1} <full | incr | monitor>'.format(sys.argv[1:], sys.argv[0])
        logger.error(msg)
        raise ProgramError(msg)


# 生成备份目录名
def generate_backup_dir(incremental=False):
    backup_dir = os.path.join(
        TARGET_PATH,
        datetime.now().strftime(DATEFMT)
    )

    if incremental:
        backup_dir += '_incr'
    else:
        backup_dir += '_base'

    return backup_dir


# 取得所有备份目录，按名称升序排列
def get_all_backup_dirs():
    dirs = []
    for obj in os.listdir(TARGET_PATH):
        full_path = os.path.join(TARGET_PATH, obj)
        if os.path.isdir(full_path):
            dirs.append(full_path)
    return sorted(dirs)


# 取得最新备份目录
# 返回：(最新目录,最新base目录,最新incr目录)
def get_last_backup_dirs():
    all_dirs = get_all_backup_dirs()

    base_dir = None
    incr_dir = None

    for path in all_dirs:
        if path.endswith('base') and (base_dir is None or path > base_dir):
            base_dir = path
        if path.endswith('incr') and (incr_dir is None or path > incr_dir):
            incr_dir = path

    return max(base_dir, incr_dir), base_dir, incr_dir


# 取得一个备份目录对应的LSN
# 返回：(FromLSN,ToLSN)
def get_lsns(backup_dir):
    from_lsn = 0
    to_lsn = 0

    with open(os.path.join(backup_dir, 'xtrabackup_checkpoints')) as fp:
        for line in fp:
            k, v = [s.strip() for s in line.split('=')]
            if k == 'from_lsn':
                from_lsn = int(v)
            if k == 'to_lsn':
                to_lsn = int(v)

    return from_lsn, to_lsn


# 取得指定起止点的全部目录，按名称升序排列
def list_dirs(from_dir, to_dir):
    dirs = []

    for path in get_all_backup_dirs():
        if from_dir <= path <= to_dir:
            dirs.append(path)

    return sorted(dirs)


# 取得除保留备份外所有旧备份目录
def get_old_backup_dirs():
    dirs = []

    if BACKUP_REDUNDANCY is None or BACKUP_REDUNDANCY <= 0:
        return dirs

    cnt = 0
    all_dirs = sorted(get_all_backup_dirs(), reverse=True)

    for path in all_dirs:
        if cnt < BACKUP_REDUNDANCY:
            if path.endswith('base'):
                cnt += 1
            continue
        else:
            dirs.append(path)

    return dirs


# 验证备份链是否完整
def check_backup_chain(base_dir, incr_dir):
    if base_dir is None:
        return False

    if incr_dir is None or incr_dir < base_dir:
        return True

    old_to_lsn = 0

    for backup_dir in list_dirs(base_dir, incr_dir):
        from_lsn, to_lsn = get_lsns(backup_dir)
        if old_to_lsn != from_lsn:
            logger.warning('Backup chain is broken, please check {0}'.format(backup_dir))
            return False
        else:
            old_to_lsn = to_lsn

    return True


# 执行命令
def execute_command(command):
    logger.info('Begin execute command: {0}'.format([cmd for cmd in command if 'password' not in cmd]))

    with open(output_file, 'a') as fp:
        process = subprocess.Popen(command, stdout=fp, stderr=subprocess.STDOUT)
        process.communicate()
        if process.returncode != 0:
            raise ProcessError(command, process.returncode)

    logger.info('Command executed')


# 记录执行事件
def record_event(backup_dir, event_name):
    with open(index_file, 'a') as f:
        record = '{0}\t{1}\t{2}\n'.format(
            backup_dir,
            event_name,
            datetime.now().strftime(DATEFMT)
        )
        f.write(record)


# 备份
def backup(backup_dir, base_dir=None):
    command = [
        XTRABACKUP,
        '--defaults-file=' + MYSQL_CNF,
        '--backup',
        '--user=' + MYSQL_USER,
        '--password=' + MYSQL_PASSWORD,
        '--target-dir=' + backup_dir
    ]

    if base_dir:
        command.extend([
            '--incremental',
            '--incremental-basedir=' + base_dir
        ])

    try:
        record_event(backup_dir, 'backup_begin')
        execute_command(command)
        record_event(backup_dir, 'backup_end')
    except Exception as exc:
        logger.error(exc)
        record_event(backup_dir, 'backup_error')
        raise exc


# 使用scp将备份复制到远端
def scp(backup_dir):
    command = [
        'scp',
        '-r',
        backup_dir,
        '{0}@{1}:{2}'.format(REMOTE_USER, REMOTE_HOST, REMOTE_PATH),
    ]

    try:
        record_event(backup_dir, 'copy_begin')
        execute_command(command)
        record_event(backup_dir, 'copy_end')
    except Exception as exc:
        logger.error(exc)
        record_event(backup_dir, 'copy_error')
        raise exc


# 获取备份执行信息供监控使用
def monitor(backup_dir, monitor_key):
    result = {
        'backup_date': 0,
        'backup_time': 0,
        'backup_type': 0,  # 0-全量 1-增量
        'backup_success': 0,  # 0-失败 1-成功
        'backup_elapsed': 0,  # 秒
        'copy_success': 0,  # 0-失败 1-成功
        'copy_elapsed': 0  # 秒
    }

    if monitor_key not in result or (not backup_dir):
        return 0

    fields = os.path.basename(backup_dir.strip(os.path.sep)).split('_')
    if len(fields) != 3:
        return 0

    result['backup_date'] = int(fields[0])
    result['backup_time'] = int(fields[1])
    result['backup_type'] = 0 if fields[2] == 'base' else 1

    step = {
        'backup_begin': None,
        'backup_end': None,
        'backup_error': None,
        'copy_begin': None,
        'copy_end': None,
        'copy_error': None}

    with open(index_file, 'r') as f:
        for line in f:
            if line:
                dir_name, event_name, occur_time = line.split('\t')
                if dir_name == backup_dir:
                    if event_name in step:
                        step[event_name] = datetime.strptime(occur_time.strip(), DATEFMT)

    result['backup_success'] = 1 if step['backup_error'] is None else 0
    if step['backup_begin'] is None or (step['backup_end'] is None and step['backup_error'] is None):
        result['backup_elapsed'] = 0
    else:
        result['backup_elapsed'] = int(((step['backup_end'] if step['backup_end'] else step['backup_error']) -
                                        step['backup_begin']).total_seconds())

    if COPY_TO_REMOTE == 'off':
        result['copy_success'] = 1
        result['copy_elapsed'] = 0
    else:
        result['copy_success'] = 1 if step['copy_error'] is None else 0
        if step['copy_begin'] is None or (step['copy_end'] is None and step['copy_error'] is None):
            result['copy_elapsed'] = 0
        else:
            result['copy_elapsed'] = int(((step['copy_end'] if step['copy_end'] else step['copy_error']) -
                                          step['copy_begin']).total_seconds())

    return result[monitor_key]


# 删除过期备份目录
def remove_old_backup_dirs():
    for path in get_old_backup_dirs():
        command = [
            'rm',
            '-rf',
            path
        ]

        try:
            execute_command(command)
        except Exception as exc:
            logger.error(exc)
            raise exc


# 删除远端过期备份目录
def remove_old_backup_dirs_ssh():
    for path in get_old_backup_dirs():
        base_name = os.path.basename(path)
        command = [
            'ssh',
            '{0}@{1}'.format(REMOTE_USER, REMOTE_HOST),
            '"rm -rf {0}"'.format(os.path.join(REMOTE_PATH, base_name))
        ]

        try:
            execute_command(command)
        except Exception as exc:
            logger.error(exc)
            raise exc


# 入口
def main():
    check_conf()

    cur_dir, cur_base_dir, cur_incr_dir = get_last_backup_dirs()

    arg = sys.argv[1].lower()

    if arg == 'monitor':
        if len(sys.argv) < 3:
            print(0)
            sys.exit(0)

        monitor_key = sys.argv[2]

        print(monitor(cur_dir, monitor_key))
    else:
        setup_log()  # 备份时才将日志写入文件

        incremental = (arg == 'incr')

        if incremental and (not check_backup_chain(cur_base_dir, cur_incr_dir)):
            logger.warning('Request a incremental backup, but there is no base full backup or the backup chain is '
                           'broken. Take full backup instead')
            incremental = False

        backup_dir = generate_backup_dir(incremental)

        if incremental:
            backup(backup_dir, cur_dir)
        else:
            backup(backup_dir)

        if COPY_TO_REMOTE.lower() == 'scp':
            scp(backup_dir)

        # 全备完成后删除过期备份
        if not incremental:
            remove_old_backup_dirs()
            if COPY_TO_REMOTE.lower() == 'scp':
                remove_old_backup_dirs_ssh()


if __name__ == '__main__':
    main()
