%define    _topdir /opt/rpmbuild/rpm/rpmbuild
Name: mysql
Version: 5.7.24
Release: 1
License: GPL

Group: Applications/Database
URL: http://www.mysql.com
BuildRoot: %{_topdir}/%{name}-%{version}-%{release}-root
#BuildRoot: %{_topdir}/%{name}-%{version}-%{release}-daemon

# BuildRequires指定编译时依赖的包
BuildRequires: cmake
BuildRequires: gcc
BuildRequires: gcc-c++
BuildRequires: perl
BuildRequires: time
BuildRequires: libaio-devel
BuildRequires: ncurses-devel
BuildRequires: openssl-devel
BuildRequires: zlib-devel
# Requires指定安装时依赖的包
Requires: perl-Data-Dumper
Packager: xxx
Autoreq: no
Source: %{name}-boost-%{version}.tar.gz
Summary: MySQL %{version}
Prefix: /usr/local/mysql

%description
The MySQL(TM) software delivers a very fast, multi-threaded, multi-user,
and robust SQL (Structured Query Language) database server. MySQL Server
is intended for mission-critical, heavy-load production systems as well
as for embedding into mass-deployed software.

%define MYSQL_USER mysql
%define MYSQL_GROUP mysql
%define __os_install_post %{nil}

%prep
%setup -n %{name}-%{version}

%build
CFLAGS="-O3 -g -static-libgcc -fno-omit-frame-pointer -fno-strict-aliasing"
CXX=g++
CXXFLAGS="-O3 -g -static-libgcc -fno-omit-frame-pointer -fno-strict-aliasing"
export CFLAGS CXX CXXFLAGS

cmake . \
  -DSYSCONFDIR:PATH=%{prefix} \
  -DCMAKE_INSTALL_PREFIX:PATH=%{prefix} \
  -DCMAKE_BUILD_TYPE:STRING=Release \
  -DWITH_DEBUG:BOOL=OFF \
  -DWITH_VALGRIND:BOOL=OFF \
  -DENABLE_DEBUG_SYNC:BOOL=OFF \
  -DWITH_EXTRA_CHARSETS:STRING=all \
  -DWITH_SSL:STRING=bundled \
  -DWITH_UNIT_TESTS:BOOL=OFF \
  -DWITH_ZLIB:STRING=bundled \
  -DWITH_PARTITION_STORAGE_ENGINE:BOOL=ON \
  -DWITH_INNOBASE_STORAGE_ENGINE:BOOL=ON \
  -DWITH_ARCHIVE_STORAGE_ENGINE:BOOL=ON \
  -DWITH_BLACKHOLE_STORAGE_ENGINE:BOOL=ON \
  -DWITH_PERFSCHEMA_STORAGE_ENGINE:BOOL=ON \
  -DDEFAULT_CHARSET=utf8 \
  -DDEFAULT_COLLATION=utf8_general_ci \
  -DWITH_EXTRA_CHARSETS=all \
  -DENABLED_LOCAL_INFILE:BOOL=ON \
  -DWITH_EMBEDDED_SERVER=0 \
  -DINSTALL_LAYOUT:STRING=STANDALONE \
  -DWITH_BOOST=./boost ;

make -j `cat /proc/cpuinfo | grep processor | wc -l`
#make

%install
make DESTDIR=$RPM_BUILD_ROOT install
cp %{_sourcedir}/my.cnf $RPM_BUILD_ROOT%{prefix}

%clean
rm -rf $RPM_BUILD_ROOT/*

%files
%defattr(-, root, root, -)
%{prefix}/*

%pre
if ! id %{MYSQL_USER} > /dev/null 2>&1 ; then
useradd -M -s /usr/sbin/nologin %{MYSQL_USER}
fi

%post
if [ -f %{prefix}/support-files/mysql.server > /dev/null 2>&1 ] && [ ! -f %{_initddir}/mysqld > /dev/null 2>&1 ]; then
cp %{prefix}/support-files/mysql.server %{_initddir}/mysqld
chmod +x %{_initddir}/mysqld
chkconfig --level 2345 mysqld on
fi

if [ -f %{_sysconfdir}/my.cnf ]; then
mv %{_sysconfdir}/my.cnf %{_sysconfdir}/my.cnf.bak
fi

echo '' >> /etc/profile
echo 'export PATH=$PATH:%{prefix}/bin' >> /etc/profile

%preun
if [ -f %{prefix}/my.cnf ]; then
mv %{prefix}/my.cnf %{_sysconfdir}/my.cnf.rpmold
fi

if [ -f %{_initddir}/mysqld ]; then
mv %{_initddir}/mysqld %{_initddir}/mysqld.bak
fi

%postun
rm -rf %{prefix}

%changelog