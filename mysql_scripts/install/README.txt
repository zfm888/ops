1. 使用root用户登录系统

2. 执行install_mysql.py

3. 根据提示创建目录、修改MySQL配置文件、初始化数据库
本步比较复杂，为防止误删文件，需核实正确后手动执行


注
1). 使用rpm目录下的脚本制作RPM包
2). install_mysql.py会安装MySQL RPM包、percona-xtrabackup、percona-toolkit、percona-zabbix-templates及依赖的库


安装完mysql后执行

1.配置文件/usr/local/mysql/my.cnf中修改server_id，innodb_buffer_pool_size，innodb_buffer_pool_instances，【按照服务器配置相应修改】其他的都保留即可
2.创建目录并修改权限：
mkdir -p /opt/mysql/{data,run,tmp}
mkdir -p /opt/mysql/log/{binlog,relaylog}
chown -R mysql:mysql /data/mysql/
4.初始化mysql：./bin/mysqld --defaults-file=/usr/local/mysql/my.cnf --initialize --user=mysql
5.密码会写到错误日志中去 /data/mysql/log/error.log
6.然后启动即可：/etc/init.d/mysqld start
7.然后登录进去修改密码即可

grant all privileges on xxxdb.* to '用户名'@'主机IP' identified by '密码';
alter user user() identified by "新密码";
grant all on *.* to 写账户用户名@'10.%' identified by '写账户密码';
grant select on *.* to 读账户用户名@'10.%' identified by '读账户密码';