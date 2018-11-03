############################
mysql_backup.py
############################
全量备份：
SHELL> python /your/path/mysql_backup.py full

增量备份：
SHELL> python /your/path/mysql_backup.py incr

最近备份信息（用于zabbix监控）：
SHELL> python /your/path/mysql_backup.py monitor <monitor_key>
其中monitor_key可以选择backup_date/backup_time/backup_type/backup_success/backup_elapsed/copy_success/copy_elapsed

注：备份所使用MySQL用户需要具有RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT ON *.*权限
