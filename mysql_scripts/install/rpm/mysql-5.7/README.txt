1. 使用root登录系统

2. 安装必需的软件/库
SHELL> yum install gcc gcc-c++ perl time cmake make bison ncurses-devel libaio-devel openssl-devel zlib-devel bzip2 rpm-build

3. 创建目录
SHELL> cd ~
SHELL> mkdir -p /opt/rpmbuild/rpm/rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

4. mysql源码包（含boost头）、my.cnf、boost源码包复制到/opt/rpmbuild/rpm/rpmbuild/SOURCES
SHELL> cp mysql-boost-5.7.24.tar.gz /opt/rpmbuild/rpm/rpmbuild/SOURCES
SHELL> cp my.cnf /opt/rpmbuild/rpm/rpmbuild/SOURCES

5. 编译打包
SHELL> rpmbuild -bb mysql-5.7.spec

6. /opt/rpmbuild/rpm/rpmbuild/RPMS/mysql-5.7.24-yff.x86_64.rpm即为需要的安装包，debuginfo包在运行中非必需

注：
1). 本说明以MySQL 5.7.24为例，请根据MySQL版本修改源码包名称、spec文件中Version定义