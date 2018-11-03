#! /usr/bin/python
# -*- coding:utf-8 -*-

from __future__ import print_function

import subprocess

MYSQL_VERSION = '5.7.24'
MYSQL_DATA_PATH = '/opt/'
MYSQL_RELEASE = '1'
MYSQL_PACKAGE_PREFIX = 'yx'


# 执行系统命令
def execute_command(command):
    print('#' * 30)

    if isinstance(command, list):
        print('执行命令:', ' '.join(command), )
    else:
        print('执行命令:', command)

    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
                             universal_newlines=True)

    for line in iter(child.stdout.readline, b''):
        print(line, end='')

    child.wait()


# 卸载部分包
command = [
    '/usr/bin/yum',
    '-y',
    'remove',
    'mariadb.x86_64',
    'mariadb-devel.x86_64'
]
#execute_command(command)

# 安装MySQL
command = [
    '/usr/bin/yum',
    '-y',
    'install',
    MYSQL_PACKAGE_PREFIX + '_mysql-{0}-{1}'.format(MYSQL_VERSION,MYSQL_RELEASE)
]
#execute_command(command)

# 安装工具
command = [
    '/usr/bin/yum',
    '-y',
    '--skip-broken',
    'install',
    'percona-xtrabackup-24',
    'percona-toolkit',
    'percona-zabbix-templates'
]
#execute_command(command)

command = [
    '/usr/bin/yum',
    '-y',
    'install',
    'httpd',
    'php',
    'php-mysql'
]
#execute_command(command)

# 提示信息-目录结构
default_dir_struct = MYSQL_DATA_PATH + '''
    └── mysql
        ├── data
        ├── log
        │   ├── binlog
        │      └── relaylog
        ├── run
        └── tmp'''

default_mkdir = '''mkdir -p {0}mysql/data
mkdir -p {0}mysql/log/binlog
mkdir -p {0}mysql/log/relaylog
mkdir -p {0}mysql/run
mkdir -p {0}mysql/tmp
chown -R mysql:mysql {0}mysql'''.format(MYSQL_DATA_PATH)

print('\033[1;31;40m')  # 红色高亮显示

print('默认目录结构为')
print(default_dir_struct)

print('请使用下面语句创建目录结构，或根据需要调整结构及MySQL配置文件/usr/local/mysql/my.cnf')
print(default_mkdir)
print()

# 提示信息-内存
total_memory_gb = None
with open('/proc/meminfo') as f:
    for line in f:
        if line.startswith('MemTotal'):
            val = line[line.index(':') + 1:].strip()
            val = val.strip('kKbB').strip()
            total_memory_gb = int(val) / 1024.0 / 1024.0
            break
print('当前系统物理内存大小为{0:.2f}GB，建议innodb_buffer_pool_size设置为: {1}G'.format(
    total_memory_gb,
    int(total_memory_gb * 0.75)))
print()

# 提示信息-初始化
init_command = None

if '5.7' in MYSQL_VERSION:
    init_command = '''cd /usr/local/mysql
./scripts/mysql_install_db --defaults-file=/usr/local/mysql/my.cnf --datadir={0}mysql/data --user=mysql'''.format(MYSQL_DATA_PATH)
else:
    init_command = '/usr/local/mysql/bin/mysqld --initialize --defaults-file=/usr/local/mysql/my.cnf ' \
                   '--datadir={0}mysql/data --user=mysql'.format(MYSQL_DATA_PATH)

print('请使用以下命令初始化数据库（根据情况修改数据目录）')
print(init_command)
print()

print('\033[0m')  # 恢复终端颜色
