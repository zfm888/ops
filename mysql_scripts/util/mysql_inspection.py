#! /usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import print_function

import socket
import os
import platform
from datetime import datetime, timedelta
from distutils import spawn
import subprocess
from collections import defaultdict
import re
import time
import argparse
import getpass

import psutil
import MySQLdb

# 功能：
#   获取MySQL及系统信息
# 注意：
#   1. 依赖psutil（https://github.com/giampaolo/psutil）
#   2. 依赖MySQL-python(Python3依赖mysqlclient)
# TODO
#   1. 增加安全相关信息的收集（SSL配置、空密码、弱密码等）
#   2. 增加Email发送功能
#   3. 增加简单的自动诊断提示

# ##########################################
# 参数设置
# ##########################################
ARGS = None


# 解析参数(本脚本用于在DB服务器上运行，因此使用unix socket连接MySQL)
def parse_args():
    global ARGS

    parser = argparse.ArgumentParser(description='MySQL and Host Information Summary')

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

    default_defer = 10
    parser.add_argument('--defer',
                        type=int,
                        default=default_defer,
                        help='defer seconds for calculate MySQL Counters, default: {0}'.format(default_defer))

    ARGS = parser.parse_args()

    if ARGS.defer <= 0:
        ARGS.defer = default_defer

    if not ARGS.password:
        ARGS.password = getpass.getpass()


# ##########################################
# 辅助
# ##########################################

PID_PATTERN = re.compile('^[0-9]+$')
DATE_FMT = '%Y-%m-%d %H:%M:%S'

_size_mapping = {
    ('B', 'B'): 1.0,
    ('B', 'K'): 1.0 * 1024,
    ('B', 'M'): 1.0 * 1024 * 1024,
    ('B', 'G'): 1.0 * 1024 * 1024 * 1024,
    ('B', 'T'): 1.0 * 1024 * 1024 * 1024 * 1024}


# 格式化文件/内存大小
def _format_size(value, from_unit='B', to_unit='G'):
    from_unit = from_unit[0].upper()
    to_unit = to_unit[0].upper()

    from_in_byte = _size_mapping[('B', from_unit)] * float(value)
    to = from_in_byte / _size_mapping[('B', to_unit)]

    return '{0:.3f} {1}'.format(to, to_unit)


# 输出Table样式结果
# https://gist.github.com/lonetwin/4721748
def print_table(rows, title=''):
    """print_table(rows)
    Prints out a table using the data in `rows`, which is assumed to be a
    sequence of sequences with the 0th element being the header.
    """

    # - figure out column widths
    widths = [len(max(columns, key=len)) for columns in zip(*rows)]

    if title:
        title_fmt = '{0:*<%d}' % (sum(widths) + 3 * (len(widths) - 1))
        print(title_fmt.format('****** ' + title + ' '))

    # - print the header
    header, data = rows[0], rows[1:]
    print(' | '.join(format(title, "%ds" % width) for width, title in zip(widths, header)))

    # - print the separator
    print('-+-'.join('-' * width for width in widths))

    # - print the data
    for row in data:
        print(" | ".join(format(cdata, "%ds" % width) for width, cdata in zip(widths, row)))

    print()


# ##########################################
# 系统相关信息
# ##########################################

SYSCTL = None


# 获取sysctl的设置
def _get_sysctl():
    global SYSCTL

    if SYSCTL is not None:
        return SYSCTL

    SYSCTL = {}
    cmd = spawn.find_executable('sysctl')
    if cmd:
        child = subprocess.Popen([cmd, '-a'], stdout=subprocess.PIPE)
        for line in child.stdout:
            k, v = str(line).split('=')
            SYSCTL[k.strip()] = v.strip()

    return SYSCTL


# 主机
def system_info():
    header = (
        'Hostname', 'Platform', 'Time Zone', 'Boot Time', 'Current Time', 'Up Interval', 'Connected User', 'SELinux')

    cmd = spawn.find_executable('getenforce')
    if cmd:
        child = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        selinux, _ = child.communicate()
    else:
        selinux = 'Unknown'

    delta = -(time.altzone if time.localtime().tm_isdst and time.daylight else time.timezone)
    delta = int(delta / 60 / 60)
    time_zone = 'UTC{0}{1}'.format(
        '+' if delta > 0 else '',
        str(delta) if delta != 0 else '')

    data = (socket.gethostname(),
            platform.platform(),
            time_zone,
            datetime.fromtimestamp(psutil.boot_time()).strftime(DATE_FMT),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            str(datetime.now() - datetime.fromtimestamp(psutil.boot_time())),
            str(len(psutil.users())),
            str(selinux).strip())

    print_table([header, data], title='System Info')


# 网络接口
def network_interface():
    duplex_name = {
        psutil.NIC_DUPLEX_FULL: 'Full',
        psutil.NIC_DUPLEX_HALF: 'Half',
        psutil.NIC_DUPLEX_UNKNOWN: 'Unknown'}

    rows = [('NIC', 'Address', 'Up', 'Duplex', 'Speed(MB)', 'MTU(Byte)',
             'Size(In)', 'Packet(In)', 'Error(In)', 'Drop(In)',
             'Size(Out)', 'Packet(Out)', 'Error(Out)', 'Drop(Out)')]

    if_addrs = psutil.net_if_addrs()
    if_stats = psutil.net_if_stats()
    if_counts = psutil.net_io_counters(pernic=True)

    for nic in if_addrs.keys():
        addr = ', '.join(info.address + ('/' + info.netmask if info.netmask else '')
                         for info in if_addrs[nic]
                         if info.family == socket.AF_INET)
        rows.append((
            nic,
            addr,

            'YES' if if_stats[nic].isup else 'NO',
            duplex_name[if_stats[nic].duplex],
            str(if_stats[nic].speed),
            str(if_stats[nic].mtu),

            _format_size(if_counts[nic].bytes_recv),
            str(if_counts[nic].packets_recv),
            str(if_counts[nic].errin),
            str(if_counts[nic].dropin),

            _format_size(if_counts[nic].bytes_sent),
            str(if_counts[nic].packets_sent),
            str(if_counts[nic].errout),
            str(if_counts[nic].dropout)))

    print_table(rows, title='Network Interface')


# 网络设置
def network_config():
    rows = [('Item', 'Value')]

    sysctl = _get_sysctl()

    for key in ('net.ipv4.tcp_fin_timeout', 'net.ipv4.ip_local_port_range', 'net.ipv4.ip_local_reserved_ports'):
        rows.append((
            key,
            sysctl.get(key, '')))

    print_table(rows, title='Network Config')


# CPU
def cpu_info():
    header = ('Physical Core', 'Logical Core', 'Model', 'Speed', 'Cache')

    models = defaultdict(int)
    speeds = defaultdict(int)
    caches = defaultdict(int)

    with open('/proc/cpuinfo') as f:
        for line in f:
            if line.strip():
                k, v = [val.strip() for val in line.split(':')]
                if k == 'model name':
                    models[v] += 1
                elif k == 'cpu MHz':
                    speeds[v] += 1
                elif k == 'cache size':
                    caches[v] += 1

    model = ', '.join(k + ' x ' + str(v) for k, v in models.items()) if models else '-'
    speed = ', '.join(k + ' x ' + str(v) for k, v in speeds.items()) if models else '-'
    cache = ', '.join(k + ' x ' + str(v) for k, v in caches.items()) if models else '-'

    data = (str(psutil.cpu_count(logical=False)),
            str(psutil.cpu_count(logical=True)),
            model, speed, cache)

    print_table([header, data], title='CPU')


# 内存
def memory():
    header = ('Total', 'Available', 'Used', 'Used %', 'Free', 'Shared', 'Buffers', 'Caches', 'Dirty',
              'vm.dirty_ratio', 'vm.dirty_background_ratio', 'vm.dirty_bytes', 'vm.dirty_background_bytes')

    info = psutil.virtual_memory()

    dirty = 0
    with open('/proc/meminfo') as f:
        for line in f:
            k, v = [val.strip() for val in line.split(':')]
            if k == 'Dirty':
                dirty = int(v.split()[0]) * 1024
                break

    sysctl = _get_sysctl()

    data = (
        _format_size(info.total),
        _format_size(info.available),
        _format_size(info.used),
        '{0:.1f}'.format(info.percent),
        _format_size(info.free),
        _format_size(info.shared),
        _format_size(info.buffers),
        _format_size(info.cached),
        _format_size(dirty),
        sysctl.get('vm.dirty_ratio', ''),
        sysctl.get('vm.dirty_background_ratio', ''),
        sysctl.get('vm.dirty_bytes', ''),
        sysctl.get('vm.dirty_background_bytes', ''))

    print_table([header, data], title='Memory')


# Swap
def swap():
    header = ('Total', 'Free', 'Used', 'Used %', 'Swap In', 'Swap Out', 'vm.swappiness')

    info = psutil.swap_memory()

    sysctl = _get_sysctl()

    data = (
        _format_size(info.total),
        _format_size(info.free),
        _format_size(info.used),
        '{0:.1f}'.format(info.percent),
        _format_size(info.sin),
        _format_size(info.sout),
        sysctl.get('vm.swappiness', ''))

    print_table([header, data], title='Swap')


# 磁盘分区
def disk_partition():
    rows = [('Device', 'Mount Point', 'File System', 'Total', 'Free', 'Used', 'Used %', 'Opts')]

    parts = psutil.disk_partitions()
    for part in parts:
        try:
            usage = psutil.disk_usage(part.mountpoint)

            total = _format_size(usage.total)
            free = _format_size(usage.free)
            used = _format_size(usage.used)
            used_pct = '{0:.1f}'.format(usage.percent)
        except:
            total = free = used = used_pct = '-'

        rows.append((
            part.device,
            part.mountpoint,
            part.fstype,
            total,
            free,
            used,
            used_pct,
            part.opts))

    print_table(rows, title='Disk Partition')


# 磁盘调度/队列
def disk_scheduler_queue():
    device_dir = '/sys/block'
    rows = [('Device', 'Scheduler', 'Queue Size')]

    for device in sorted(os.listdir(device_dir)):
        full = os.path.join(device_dir, device)
        if os.path.isdir(full):
            scheduler = ''
            queue_size = ''

            with open(os.path.join(full, 'queue/scheduler')) as f:
                vals = f.readline().split()
                for val in vals:
                    if val.startswith('[') and val.endswith(']'):
                        scheduler = val
                        break

            with open(os.path.join(full, 'queue/nr_requests')) as f:
                queue_size = f.readline().strip()

            rows.append((device, scheduler, queue_size))

    print_table(rows, title='Disk Scheduler & Queue')


# 文件系统状态
def filesystem_state():
    rows = [('State', 'Values')]

    state_dir = '/proc/sys/fs'
    for state in ('dentry-state', 'file-nr', 'inode-nr'):
        with open(os.path.join(state_dir, state)) as f:
            val = f.readline().strip()
            rows.append((state, val))

    print_table(rows, title='File System')


# LVM卷
def lvm_lv():
    rows = []

    cmd = spawn.find_executable('lvs')

    if cmd:
        child = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        for line in child.stdout:
            rows.append((str(line).rstrip(),))

        print_table(rows, title='LVM Logical Volume')


# LVM卷组
def lvm_vg():
    rows = []

    cmd = spawn.find_executable('vgs')

    if cmd:
        child = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        for line in child.stdout:
            rows.append((str(line).rstrip(),))

        print_table(rows, title='LVM Volume Group')


# 进程
def top_process():
    top_num = 10

    rows = []
    add = False
    count = 0

    cmd = spawn.find_executable('top')
    if cmd:
        child = subprocess.Popen([cmd, '-bn', '1'], stdout=subprocess.PIPE)
        for line in child.stdout:
            line = str(line).rstrip()
            if not add:
                if line.lstrip().startswith('PID'):
                    add = True
                    rows.append((line,))
                else:
                    continue
            else:
                if count < top_num:
                    rows.append((line,))
                    count += 1
                else:
                    break

        print_table(rows, title='Top Process')


# OOM进程
def oom_process():
    rows = [('PID', 'Command', 'OOM')]

    cmd = spawn.find_executable('ps')
    if cmd:
        child = subprocess.Popen([cmd, '-eo', 'pid,comm'], stdout=subprocess.PIPE)
        for line in child.stdout:
            pid, command = str(line).split(None, 1)

            if PID_PATTERN.match(pid):
                oom = _oom_of_pid(pid)

                if oom != '0':
                    rows.append((pid, command.strip(), oom))
            else:
                continue

        print_table(rows, title='OOM Process')


def _oom_of_pid(pid):
    file_path = '/proc/{0}/oom_score_adj'.format(pid)

    try:
        with open(file_path) as f:
            return f.readline().strip()
    except:
        return '0'


# ##########################################
# MySQL信息
# ##########################################
CONN = SYSTEM_VARS = STATUS_VARS = STATUS_DEFER = None


# 获取数据库连接
def _connect():
    global CONN

    if CONN is not None:
        return CONN

    CONN = MySQLdb.connect(host='localhost', unix_socket=ARGS.socket, user=ARGS.user, passwd=ARGS.password)

    return CONN


# MySQL系统变量
def _mysql_system_var():
    global SYSTEM_VARS

    if SYSTEM_VARS is not None:
        return SYSTEM_VARS

    cur = _connect().cursor()
    cur.execute("SHOW GLOBAL VARIABLES")
    rows = cur.fetchall()
    cur.close()

    SYSTEM_VARS = {}
    for row in rows:
        SYSTEM_VARS[row[0]] = row[1]

    return SYSTEM_VARS


# MySQL状态变量
def _mysql_status_var(defer=False):
    global STATUS_VARS
    global STATUS_DEFER

    if STATUS_VARS is not None and STATUS_DEFER is not None:
        return STATUS_DEFER if defer else STATUS_VARS

    STATUS_VARS = _get_status_var()

    sleep = ARGS.defer
    while sleep > 0:
        print('Please wait for {0} second{1}'.format(
            sleep,
            's' if sleep > 1 else ''
        ))
        time.sleep(1)
        sleep -= 1

    STATUS_DEFER = _get_status_var()

    return STATUS_DEFER if defer else STATUS_VARS


def _get_status_var():
    conn = _connect()

    cur = conn.cursor()
    cur.execute("SHOW GLOBAL STATUS")
    rows = cur.fetchall()

    status = {}
    for row in rows:
        status[row[0]] = row[1]

    # 自定义状态--当前时间
    cur.execute("SELECT NOW()")
    val = cur.fetchone()[0]
    status['_ext_current_time'] = val

    # 自定义状态--Master状态
    cur.execute("SHOW MASTER STATUS")
    binlog_file, binlog_position, binlog_do_db, binlog_ignore_db, executed_gtid_set = cur.fetchone()
    cur.close()
    status['_ext_binlog_file'] = binlog_file
    status['_ext_binlog_position'] = binlog_position
    status['_ext_binlog_do_db'] = binlog_do_db
    status['_ext_binlog_ignore_db'] = binlog_ignore_db
    status['_ext_executed_gtid_set'] = executed_gtid_set

    return status


# 运行的MySQL实例
def mysql_instance():
    rows = [('PID', 'Executable', 'Port', 'Socket', 'Data Dir', 'OOM', 'Nice')]

    cmd = spawn.find_executable('ps')

    if cmd:
        child = subprocess.Popen([cmd, '-eo', 'pid,comm,ni,command'], stdout=subprocess.PIPE)
        for line in child.stdout:
            pid, short_cmd, nice, full_cmd = str(line).split(None, 3)
            if PID_PATTERN.match(pid) and short_cmd == 'mysqld':
                executable = port = socket_file = datadir = ''
                args = full_cmd.split()
                for arg in args:
                    if arg.endswith('mysqld'):
                        executable = arg
                    elif arg.startswith('--port'):
                        port = arg[arg.index('=') + 1:]
                    elif arg.startswith('--socket'):
                        socket_file = arg[arg.index('=') + 1:]
                    elif arg.startswith('--datadir'):
                        datadir = arg[arg.index('=') + 1:]
                oom = _oom_of_pid(pid)

                rows.append((pid, executable, port, socket_file, datadir, oom, nice))

        print_table(rows, title='MySQL Instance')


# MySQL基本信息
def mysql_baseinfo():
    header = ('Version', 'Compiled On', 'Server ID', 'Server UUID', 'Time Zone',
              'Current Time', 'Start Time', 'Up Interval', 'Bind Address', 'Port')

    system_var = _mysql_system_var()
    status_var = _mysql_status_var()

    time_zone = system_var['time_zone']
    if time_zone == 'SYSTEM':
        time_zone = system_var['system_time_zone']

    up_interval = timedelta(seconds=int(status_var['Uptime']))

    data = (
        system_var['version'] + ' ' + system_var['version_comment'],
        system_var['version_compile_os'] + ' ' + system_var['version_compile_machine'],
        system_var['server_id'],
        system_var['server_uuid'],
        time_zone,
        status_var['_ext_current_time'].strftime(DATE_FMT),
        (status_var['_ext_current_time'] - up_interval).strftime(DATE_FMT),
        str(up_interval),
        system_var['bind_address'],
        system_var['port'])

    print_table([header, data], title='MySQL Base Info')


# MySQL文件设置
def mysql_file_setting():
    rows = [('Name', 'Value', 'Exist', 'Size', 'Change Time')]

    system_var = _mysql_system_var()
    for name in (
            'basedir', 'datadir', 'pid_file', 'socket',
            'log_error', 'general_log_file', 'slow_query_log_file',
            'innodb_data_home_dir', 'innodb_log_group_home_dir', 'innodb_undo_directory',
            'plugin_dir', 'character_sets_dir', 'lc_messages_dir', 'tmpdir',
            'log_output'):
        val = system_var.get(name, '')

        exist = size = change_time = ''
        if os.path.isabs(val):
            if os.path.exists(val):
                exist = 'YES'
                if os.path.isfile(val):
                    stat = os.stat(val)
                    size = _format_size(stat.st_size, to_unit='M')
                    change_time = datetime.fromtimestamp(stat.st_mtime).strftime(DATE_FMT)
            else:
                exist = 'NO'

        rows.append((name, val, exist, size, change_time))

    print_table(rows, title='MySQL File Setting')


# BinLog
def mysql_binlog():
    # 设置部分
    setting_header = ('Base Name', 'Index File', 'BinLog Format', 'Enabled', 'GTID Mode', 'Enforce GTID Consistency',
                      'Sync Binlog', 'Max Size', 'Expire Days', 'binlog_do_db', 'binlog_ignore_db')

    system_var = _mysql_system_var()
    status_var = _mysql_status_var()

    setting_data = (
        system_var.get('log_bin_basename', ''),
        system_var.get('log_bin_index', ''),
        system_var.get('binlog_format', ''),
        system_var.get('log_bin', ''),
        system_var.get('gtid_mode', ''),
        system_var.get('enforce_gtid_consistency', ''),
        system_var.get('sync_binlog', ''),
        _format_size(int(system_var.get('max_binlog_size', '0')), to_unit='M'),
        system_var.get('expire_logs_days', ''),
        status_var.get('_ext_binlog_do_db', ''),
        status_var.get('_ext_binlog_ignore_db', '')
    )

    print_table([setting_header, setting_data], title='MySQL Binlog Setting')

    # 实际Binlog统计部分
    stats_header = ('Count', 'Total Size', 'Avg Size', 'Max Size', 'Min Size')

    cur = _connect().cursor()
    count = cur.execute("SHOW BINARY LOGS")
    binlogs = cur.fetchall()
    cur.close()

    total_size = min_size = max_size = 0
    if count > 0:
        for binlog in binlogs:
            size = binlog[1]
            total_size += size

            if max_size < size:
                max_size = size

            if min_size == 0 or min_size > size:
                min_size = size

    avg_size = (total_size * 1.0 / count if count else 0)

    stats_data = (
        str(count),
        _format_size(total_size, to_unit='M'),
        _format_size(avg_size, to_unit='M'),
        _format_size(max_size, to_unit='M'),
        _format_size(min_size, to_unit='M'))

    print_table([stats_header, stats_data], title='MySQL Binlog Stats')


# 数据库概览
def mysql_database():
    rows = [('DB Type', 'DB Name', 'Engine', 'Table Type', 'Table Num', 'Total Size')]

    cur = _connect().cursor()
    cur.execute("""select
    t.db_type,t.TABLE_SCHEMA,t.ENGINE,t.TABLE_TYPE,
    count(*) as table_num,
    sum(ifnull(t.DATA_LENGTH,0)+ifnull(t.INDEX_LENGTH,0)) as total_length
from
(
    select
        case
            when TABLE_SCHEMA in ('mysql','information_schema','performance_schema','sys') then 'SYSTEM'
            else 'USER'
        end as db_type,
        TABLE_SCHEMA,ifnull(ENGINE,'') as ENGINE,TABLE_TYPE,DATA_LENGTH,INDEX_LENGTH
    from information_schema.TABLES
) t
group by t.db_type,t.TABLE_SCHEMA,t.ENGINE,t.TABLE_TYPE
order by t.db_type,t.TABLE_SCHEMA,t.ENGINE,t.TABLE_TYPE""")
    recs = cur.fetchall()
    cur.close()

    for db_type, db_name, engine, table_type, table_num, total_size in recs:
        rows.append((
            db_type, db_name, engine, table_type,
            str(table_num),
            _format_size(total_size)))

    print_table(rows, title='Database Summary')


# 最大的表
def mysql_top_size_table():
    rows = [('DB Name', 'Table Name', 'Engine', 'Row Num', 'Total Size', 'Data Size', 'Index Size')]

    top_num = 10

    cur = _connect().cursor()
    cur.execute("""select
    TABLE_SCHEMA,TABLE_NAME,ENGINE,TABLE_ROWS,
    ifnull(DATA_LENGTH,0)+ifnull(INDEX_LENGTH,0) as total_length,
    DATA_LENGTH,INDEX_LENGTH
from information_schema.TABLES
order by total_length desc
limit {0}""".format(top_num))
    recs = cur.fetchall()
    cur.close()

    for db_name, table_name, engine, row_num, total_size, data_size, index_size in recs:
        rows.append((
            db_name, table_name, engine,
            str(row_num),
            _format_size(total_size, to_unit='M'),
            _format_size(data_size, to_unit='M'),
            _format_size(index_size, to_unit='M')))

    print_table(rows, title='Top Size Table')


# MySQL插件
def mysql_plugin():
    rows = [('Name', 'Status', 'Type', 'Library', 'Load Option')]

    cur = _connect().cursor()
    cnt = cur.execute("""select p.PLUGIN_NAME, p.PLUGIN_STATUS, p.PLUGIN_TYPE, p.PLUGIN_LIBRARY,p.LOAD_OPTION
from information_schema.PLUGINS p
where p.PLUGIN_LIBRARY is not null""")
    plugins = cur.fetchall()
    cur.close()

    if cnt > 0:
        for name, status, plugin_type, library, load_option in plugins:
            rows.append((name, status, plugin_type, library, load_option))

    print_table(rows, title='MySQL Plugin')


# 会话
def mysql_process():
    rows = [('User', 'Host', 'Command', 'State', 'Num', 'Total Time', 'Max Time')]

    cur = _connect().cursor()
    cur.execute("""select
    p.USER,p.HOST,p.COMMAND,p.STATE,
    count(*) as num,
    sum(p.`TIME`) as total_time,
    max(p.`TIME`) as max_time
from
(
    select
        SUBSTRING_INDEX(HOST, ':', 1) as host,
        USER,COMMAND,`TIME`,STATE
    from information_schema.PROCESSLIST
) p
group by p.USER,p.HOST,p.COMMAND,p.STATE
order by p.USER,p.HOST,p.COMMAND,p.STATE""")
    recs = cur.fetchall()
    cur.close()

    for user, host, command, state, num, total_time, max_time in recs:
        rows.append((user, host, command, state,
                     str(num),
                     str(total_time),
                     str(max_time)))

    print_table(rows, title='MySQL Process')


# 复制
def mysql_replication():
    rows = [('Category', 'Item', 'Value')]

    # 作为Slave
    category = 'As Slave'

    system_var = _mysql_system_var()
    for item in ('relay_log', 'relay_log_basename', 'relay_log_index', 'relay_log_info_file', 'slave_load_tmpdir',
                 'master_info_repository', 'relay_log_info_repository',):
        rows.append((category, item,
                     system_var.get(item, '')))

    cur = _connect().cursor()
    cnt = cur.execute('SHOW SLAVE STATUS')
    fields = [f[0] for f in cur.description]
    rec = cur.fetchone()

    if cnt > 0:
        for item in ('Master_Host', 'Master_Port', 'Auto_Position', 'Slave_IO_State', 'Last_IO_Errno', 'Last_IO_Error',
                     'Slave_SQL_Running_State', 'Last_SQL_Errno', 'Last_SQL_Error', 'Seconds_Behind_Master',
                     'Relay_Log_Space'):
            idx = fields.index(item)

            rows.append((category, item,
                         str(rec[idx]) if item != 'Relay_Log_Space' else _format_size(rec[idx], to_unit='M')))
    else:
        rows.append((category, 'Is a Slave', 'NO'))

    # 作为Master
    category = 'As Master'
    cnt = cur.execute("""select p.auto_position, count(*) as num
from
(
    select
        case
            when COMMAND like '%GTID%' then 'Y'
            else 'N'
        end as auto_position
    from information_schema.PROCESSLIST
    where COMMAND like 'Binlog Dump%'
) p
group by p.auto_position""")
    recs = cur.fetchall()
    cur.close()

    if cnt > 0:
        for auto_position, num in recs:
            rows.append((category,
                         'Slave Num (GTID: {0})'.format(auto_position),
                         str(num)))
    else:
        rows.append((category, 'Connected Slave', '0'))

    # 半同步复制配置
    system_var = _mysql_system_var()
    for item in ('rpl_semi_sync_master_enabled', 'rpl_semi_sync_master_timeout', 'rpl_semi_sync_slave_enabled',
                 'rpl_semi_sync_master_trace_level', 'rpl_semi_sync_slave_trace_level',
                 'rpl_semi_sync_master_wait_for_slave_count', 'rpl_semi_sync_master_wait_no_slave',
                 'rpl_semi_sync_master_wait_point'):
        if item in system_var:
            rows.append(('Semi Sync Setting', item, system_var[item]))

    # 半同步复制状态
    status_var = _mysql_status_var()
    for item in ('Rpl_semi_sync_master_status', 'Rpl_semi_sync_slave_status', 'Rpl_semi_sync_master_clients',
                 'Rpl_semi_sync_master_net_avg_wait_time', 'Rpl_semi_sync_master_net_wait_time',
                 'Rpl_semi_sync_master_net_waits', 'Rpl_semi_sync_master_no_times', 'Rpl_semi_sync_master_no_tx',
                 'Rpl_semi_sync_master_timefunc_failures', 'Rpl_semi_sync_master_tx_avg_wait_time',
                 'Rpl_semi_sync_master_tx_wait_time', 'Rpl_semi_sync_master_tx_waits',
                 'Rpl_semi_sync_master_wait_pos_backtraverse', 'Rpl_semi_sync_master_wait_sessions',
                 'Rpl_semi_sync_master_yes_tx'):
        if item in status_var:
            rows.append(('Semi Sync Status', item, status_var[item]))

    print_table(rows, title='MySQL Replication')


# 状态计数
def mysql_counter():
    status_var = _mysql_status_var()
    status_defer = _mysql_status_var(defer=True)
    defer_secs = ARGS.defer

    non_counter = ('Compression', 'Delayed_insert_threads', 'Innodb_buffer_pool_pages_data',
                   'Innodb_buffer_pool_pages_dirty', 'Innodb_buffer_pool_pages_free',
                   'Innodb_buffer_pool_pages_latched', 'Innodb_buffer_pool_pages_misc',
                   'Innodb_buffer_pool_pages_total', 'Innodb_data_pending_fsyncs', 'Innodb_data_pending_reads',
                   'Innodb_data_pending_writes', 'Innodb_os_log_pending_fsyncs', 'Innodb_os_log_pending_writes',
                   'Innodb_page_size', 'Innodb_row_lock_current_waits', 'Innodb_row_lock_time_avg',
                   'Innodb_row_lock_time_max', 'Key_blocks_not_flushed', 'Key_blocks_unused', 'Key_blocks_used',
                   'Last_query_cost', 'Max_used_connections', 'Ndb_cluster_node_id', 'Ndb_config_from_host',
                   'Ndb_config_from_port', 'Ndb_number_of_data_nodes', 'Not_flushed_delayed_rows', 'Open_files',
                   'Open_streams', 'Open_tables', 'Prepared_stmt_count', 'Qcache_free_blocks', 'Qcache_free_memory',
                   'Qcache_queries_in_cache', 'Qcache_total_blocks', 'Rpl_status', 'Slave_open_temp_tables',
                   'Slave_running', 'Ssl_cipher', 'Ssl_cipher_list', 'Ssl_ctx_verify_depth', 'Ssl_ctx_verify_mode',
                   'Ssl_default_timeout', 'Ssl_session_cache_mode', 'Ssl_session_cache_size', 'Ssl_verify_depth',
                   'Ssl_verify_mode', 'Ssl_version', 'Tc_log_max_pages_used', 'Tc_log_page_size', 'Threads_cached',
                   'Threads_connected', 'Threads_running', 'Uptime')

    rows = [('Variable', 'Begin', 'End',
             '{0} Seconds'.format(defer_secs),
             'Per Second')]

    for var in sorted(status_var.keys()):
        if (not var.startswith('_ext_')) and (not any(item for item in non_counter if item in var)):
            try:
                begin_val = int(status_var[var])
                end_val = int(status_defer[var])

                if begin_val != 0 and end_val != 0:
                    diff = end_val - begin_val
                    per_sec = diff * 1.0 / defer_secs

                    rows.append((var,
                                 str(begin_val),
                                 str(end_val),
                                 str(diff) if diff != 0 else '',
                                 '{0:.2f}'.format(per_sec) if diff != 0 else ''))
            except ValueError:
                pass

    print_table(rows, title='MySQL Counter')


# 缓存（不含InnoDB）
def mysql_misc_cache():
    rows = [('Category', 'Item', 'Value')]

    system_var = _mysql_system_var()
    status_var = _mysql_status_var()

    # Table Cache部分
    category = 'Table Cache'
    cache_size = int(system_var['table_open_cache'] if 'table_open_cache' in system_var else system_var['table_cache'])
    used_size = int(status_var['Open_tables'])
    used_pct = used_size * 100.0 / cache_size if cache_size > 0 else 0
    rows.append((category, 'Max Size', str(cache_size)))
    rows.append((category, 'Used Size', str(used_size)))
    rows.append((category, 'Used', '{0:.2f}%'.format(used_pct)))

    # MyISAM Key Cache部分
    category = 'MyISAM Key Cache'
    cache_size = int(system_var['key_buffer_size'])
    block_size = int(system_var['key_cache_block_size'])
    used_size = cache_size - block_size * int(status_var['Key_blocks_unused'])
    used_pct = used_size * 100.0 / cache_size if cache_size > 0 else 0
    unflushed_size = block_size * int(status_var['Key_blocks_not_flushed'])
    unflushed_pct = unflushed_size * 100.0 / cache_size if cache_size > 0 else 0
    rows.append((category, 'Cache Size', _format_size(cache_size, to_unit='M')))
    rows.append((category, 'Used Size', _format_size(used_size, to_unit='M')))
    rows.append((category, 'Used', '{0:.2f}%'.format(used_pct)))
    rows.append((category, 'Unflushed Size', _format_size(unflushed_size, to_unit='M')))
    rows.append((category, 'Unflushed', '{0:.2f}%'.format(unflushed_pct)))

    # Query Cache部分
    category = 'Query Cache'
    cache_type = system_var.get('query_cache_type', 'OFF')
    cache_size = int(system_var['query_cache_size'])
    used_size = cache_size - int(status_var['Qcache_free_memory'])
    used_pct = used_size * 100.0 / cache_size if cache_size > 0 else 0
    hit_cnt = int(status_var['Qcache_hits'])
    insert_cnt = int(status_var['Qcache_inserts'])
    hit_pct = hit_cnt * 100.0 / insert_cnt if insert_cnt > 0 else 0
    rows.append((category, 'Type', cache_type))
    rows.append((category, 'Cache Size', _format_size(cache_size, to_unit='M')))
    rows.append((category, 'Used Size', _format_size(used_size, to_unit='M')))
    rows.append((category, 'Used', '{0:.2f}%'.format(used_pct)))
    rows.append((category, 'Hit Ratio', '{0:.2f}%'.format(hit_pct)))

    print_table(rows, title='MySQL Misc Cache')


# 重要变量
def mysql_important_variable():
    rows = [('Category', 'Item', 'Value')]

    system_var = _mysql_system_var()
    status_var = _mysql_status_var()

    # 系统变量
    category = 'System'
    for item in ('default_storage_engine', 'auto_increment_increment', 'auto_increment_offset', 'flush_time',
                 'init_connect', 'init_file', 'sql_mode', 'character_set_database', 'character_set_server',
                 'character_set_system', 'character_set_client', 'character_set_connection'):
        rows.append((category, item, system_var.get(item, '')))

    for item in ('join_buffer_size', 'sort_buffer_size', 'read_buffer_size', 'read_rnd_buffer_size', 'thread_stack'):
        rows.append((category, item,
                     _format_size(int(system_var.get(item, '0')), to_unit='K')))

    for item in ('bulk_insert_buffer_size', 'max_heap_table_size', 'tmp_table_size', 'max_allowed_packet'):
        rows.append((category, item,
                     _format_size(int(system_var.get(item, '0')), to_unit='M')))

    # 状态变量
    category = 'Status'
    for item in ('Com_lock_tables', 'Com_xa_start', 'Com_stmt_prepare', 'Prepared_stmt_count', 'Ssl_accepts'):
        rows.append((category, item, status_var.get(item, '')))

    print_table(rows, title='MySQL Important Variable')


# InnoDB
def mysql_innodb():
    rows = [('Item', 'Value')]

    system_var = _mysql_system_var()
    status_var = _mysql_status_var()

    # Buffer Pool
    rows.append(('Buffer Pool Size', _format_size(int(system_var['innodb_buffer_pool_size']))))
    rows.append(('Buffer Pool Instance', system_var['innodb_buffer_pool_instances']))

    bp_total = int(status_var['Innodb_buffer_pool_pages_total'])
    bp_free = int(status_var['Innodb_buffer_pool_pages_free'])
    bp_dirty = int(status_var['Innodb_buffer_pool_pages_dirty'])
    bp_used = bp_total - bp_free
    bp_used_pct = bp_used * 100.0 / bp_total if bp_total > 0 else 0
    bp_dirty_pct = bp_dirty * 100.0 / bp_total if bp_total > 0 else 0
    rows.append(('Buffer Pool Used', '{0:.2f}%'.format(bp_used_pct)))
    rows.append(('Buffer Pool Dirty', '{0:.2f}%'.format(bp_dirty_pct)))

    # File/IO
    rows.append(('File Per Table', system_var['innodb_file_per_table']))
    rows.append(('Page Size', _format_size(int(system_var['innodb_page_size']), to_unit='K')))
    rows.append(('Flush Method', system_var['innodb_flush_method']))
    rows.append(('Double Write', system_var['innodb_doublewrite']))
    rows.append(('Checksum', system_var['innodb_checksums']))
    rows.append(('Read IO Thread', system_var['innodb_read_io_threads']))
    rows.append(('Write IO Thread', system_var['innodb_write_io_threads']))
    rows.append(('IO Capacity', system_var['innodb_io_capacity']))
    rows.append(('Adaptive Flush', system_var['innodb_adaptive_flushing']))

    # Redo Log
    rows.append(('Log File Size', _format_size(int(system_var['innodb_log_file_size']), to_unit='M')))
    rows.append(('Log File Num', system_var['innodb_log_files_in_group']))
    rows.append(('Flush Log At Trx Commit', system_var['innodb_flush_log_at_trx_commit']))
    rows.append(('Log Buffer Size', _format_size(int(system_var['innodb_log_buffer_size']), to_unit='M')))

    # Transaction/Concurrency
    rows.append(('Trx Isolation Level', system_var['tx_isolation']))
    rows.append(('XA Support', system_var['innodb_support_xa']))
    rows.append(('Thread Concurrency', system_var['innodb_thread_concurrency']))
    rows.append(('Concurrency Ticket', system_var['innodb_concurrency_tickets']))
    rows.append(('Commit Concurrency', system_var['innodb_commit_concurrency']))

    # Internal Stats ------------------------------------------------------------
    cur = _connect().cursor()
    cur.execute("SHOW ENGINE InnoDB STATUS")
    lines = cur.fetchone()[2].split('\n')
    cur.close()

    idx = 0
    for line in lines:
        if line.startswith('LATEST DETECTED DEADLOCK'):
            idx += 2
            deadlock_time = lines[idx]
            deadlock_time = deadlock_time[:deadlock_time.rindex(' ')]
            rows.append(('Latest Deadlock Time', deadlock_time))  # 最近死锁时间
            break
        idx += 1

    # ----------
    tx_section = False
    idx = 0
    cnt_stats = defaultdict(int)
    time_stats = defaultdict(list)
    undo_max = undo_cnt = undo_total = 0
    tx_his_list_len = ''
    for line in lines:
        if (not tx_section) and line.startswith('TRANSACTIONS'):
            tx_section = True
            continue

        if tx_section:
            idx += 1
            if line.startswith('---TRANSACTION'):
                tx_state = line[line.index(',') + 1:]
                if ' sec' in tx_state:
                    fields = tx_state.split()
                    state = fields[0]
                    sec = float(fields[1])

                    cnt_stats[state] += 1
                    time_stats[state].append(sec)
                else:
                    state = tx_state

                    cnt_stats[state] += 1
                    time_stats[state].append(0.0)
                continue
            if 'undo log entries' in line:
                undo = int(line.split()[-1])
                if undo > undo_max:
                    undo_max = undo
                    undo_cnt += 1
                    undo_total += undo
                continue
            if line.startswith('History list length'):
                tx_his_list_len = line.split()[3].strip()
                continue
            if line.startswith('----') and idx > 1:
                break
    for state in sorted(cnt_stats.keys()):
        # 事务状态统计
        rows.append(('Tx State ({0})'.format(state),
                     'Num: {0}, Avg Age: {1:.2f} Seconds, Max Age: {2:.2f} Seconds'.format(
                         cnt_stats[state],
                         sum(time_stats[state]) / cnt_stats[state],
                         max(time_stats[state]))))
    rows.append(('Tx History List Len', tx_his_list_len))  # 事务历史列表
    rows.append(('Tx Undo Entry',  # Undo统计
                 'Tx Num: {0}, Total: {1}, Max: {2}, Avg: {3:.2f}'.format(
                     undo_cnt,
                     undo_total,
                     undo_max,
                     undo_total * 1.0 / undo_cnt if undo_cnt > 0 else 0)))

    # ----------
    file_io_section = False
    idx = 0
    vals = []
    for line in lines:
        if line.startswith('FILE I/O'):
            file_io_section = True
            continue

        if file_io_section:
            idx += 1
            if line.startswith('Pending'):
                vals.append(line.strip())
                continue

            if line.lstrip().startswith('ibuf'):
                if len(vals) > 0:
                    vals[-1] = vals[-1] + ' ' + line.strip()
                else:
                    vals.append(line.strip())
                continue

            if line.startswith('---') and idx > 1:
                break
    if vals:
        # File IO
        rows.append(('File IO', '; '.join(vals)))

    # ----------
    buffer_pool_section = False
    idx = 0
    vals = []
    for line in lines:
        if line.startswith('BUFFER POOL AND MEMORY'):
            buffer_pool_section = True
            continue

        if buffer_pool_section:
            idx += 1
            if line.startswith('Pending'):
                vals.append(line.strip())
                continue

            if line.startswith('---') and idx > 1:
                break
    if vals:
        # Buffer Pool
        rows.append(('Buffer Pool', '; '.join(vals)))

    # ----------
    row_oper_section = False
    idx = 0
    vals = []
    for line in lines:
        if line.startswith('ROW OPERATIONS'):
            row_oper_section = True
            continue

        if row_oper_section:
            idx += 1
            if 'queries' in line or 'views' in line:
                vals.append(line.strip())
                continue

            if line.startswith('---') and idx > 1:
                break
    if vals:
        # Row Operation
        rows.append(('Row Operation', '; '.join(vals)))

    # ----------
    log_section = False
    idx = 0
    lsn_new = lsn_log_flush = lsn_page_flush = lsn_checkpooint = 0
    for line in lines:
        if line.startswith('LOG'):
            log_section = True
            continue

        if log_section:
            idx += 1
            line = line.strip()
            if line.startswith('Log sequence number'):
                lsn_new = int(line.split()[-1])
                continue
            if line.startswith('Log flushed up to'):
                lsn_log_flush = int(line.split()[-1])
                continue
            if line.startswith('Pages flushed up to'):
                lsn_page_flush = int(line.split()[-1])
                continue
            if line.startswith('Last checkpoint at'):
                lsn_checkpooint = int(line.split()[-1])
                continue
            if line.startswith('---') and idx > 1:
                break
    rows.append(('LSN', str(lsn_new)))
    rows.append(('LSN Gap - Log Flush', str(lsn_new - lsn_log_flush)))
    rows.append(('LSN Gap - Pages Flush', str(lsn_new - lsn_page_flush)))
    rows.append(('LSN Gap - Checkpoint', str(lsn_new - lsn_checkpooint)))
    # Internal Stats End------------------------------------------------------------

    print_table(rows, title='MySQL InnoDB')


# 安全（空密码、Old、弱密码）

# ##########################################
# 入口
# ##########################################
def main():
    # 获得MySQL连接参数
    parse_args()

    # 获得MySQL变量（由于获取MySQL状态变量需要等待，最先执行可以保证内容连续）
    _mysql_system_var()
    _mysql_status_var()

    # 系统信息
    system_info()
    cpu_info()
    memory()
    swap()
    disk_partition()
    disk_scheduler_queue()
    filesystem_state()
    lvm_lv()
    lvm_vg()
    network_interface()
    network_config()
    top_process()
    oom_process()

    # MySQL信息
    mysql_instance()
    mysql_baseinfo()
    mysql_file_setting()
    mysql_binlog()
    mysql_database()
    mysql_top_size_table()
    mysql_replication()
    mysql_innodb()
    mysql_counter()
    mysql_process()
    mysql_plugin()
    mysql_important_variable()
    mysql_misc_cache()

    # 关闭MySQL连接
    _connect().close()


if __name__ == '__main__':
    main()
