%define app openresty
Name:           yx_%{app}
Version: %{_ver}
Release: %{_rel}
Summary:        OpenResty, scalable web platform by extending NGINX with Lua

Group: XXX Group

# BSD License (two clause)
# http://www.freebsd.org/copyright/freebsd-license.html
License: Commercial
URL:            https://openresty.org/

#Source0:        https://openresty.org/download/openresty-%{version}.tar.gz
#Source1:        openresty.init
Source0: %{app}-%{version}.tar.gz
# Source1: openssl-1.0.2h.tar.gz
#Source1: resty/http.lua
#Source2: resty/http_headers.lua

#Patch0:         openresty-%{version}.patch

BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)

#BuildRequires:  gcc, make, perl, systemtap-sdt-devel
BuildRequires:  gcc, make, perl
#BuildRequires:  zlib-devel >= 1.2.8
BuildRequires:  zlib-devel
BuildRequires:  openssl-devel >= 1.0.2h-5
#BuildRequires:  pcre-devel >= 8.39
BuildRequires:  pcre-devel
#Requires:       zlib >= 1.2.8
Requires:       zlib
Requires:       openssl
#Requires:       pcre >= 8.39
Requires:       pcre

# for /sbin/service
#Requires(post)  chkconfig
#Requires(preun): chkconfig, initscripts

AutoReqProv:        no

%define orprefix            %{_usr}/local/%{app}
%define zlib_prefix         %{orprefix}/zlib
%define pcre_prefix         %{orprefix}/pcre
%define openssl_prefix      %{orprefix}/openssl


%description
This package contains the core server for OpenResty. Built for production
uses.

OpenResty is a full-fledged web platform by integrating the standard Nginx
core, LuaJIT, many carefully written Lua libraries, lots of high quality
3rd-party Nginx modules, and most of their external dependencies. It is
designed to help developers easily build scalable web applications, web
services, and dynamic web gateways.

By taking advantage of various well-designed Nginx modules (most of which
are developed by the OpenResty team themselves), OpenResty effectively
turns the nginx server into a powerful web app server, in which the web
developers can use the Lua programming language to script various existing
nginx C modules and Lua modules and construct extremely high-performance
web applications that are capable to handle 10K ~ 1000K+ connections in
a single box.


%package resty

Summary:        OpenResty command-line utility, resty
Group: Reorient Group
Requires:       perl, %{name}

#%if 0%{?fedora} >= 10 || 0%{?rhel} >= 6 || 0%{?centos} >= 6
#BuildArch:      noarch
#%endif


%description resty
This package contains the "resty" command-line utility for OpenResty, which
runs OpenResty Lua scripts on the terminal using a headless NGINX behind the
scene.

OpenResty is a full-fledged web platform by integrating the standard Nginx
core, LuaJIT, many carefully written Lua libraries, lots of high quality
3rd-party Nginx modules, and most of their external dependencies. It is
designed to help developers easily build scalable web applications, web
services, and dynamic web gateways.


%package doc

Summary:        OpenResty documentation tool, restydoc
Group: XXX Group
Requires:       perl
Provides:       restydoc, restydoc-index, md2pod.pl

#%if 0%{?fedora} >= 10 || 0%{?rhel} >= 6 || 0%{?centos} >= 6
#BuildArch:      noarch
#%endif


%description doc
This package contains the official OpenResty documentation index and
the "restydoc" command-line utility for viewing it.

OpenResty is a full-fledged web platform by integrating the standard Nginx
core, LuaJIT, many carefully written Lua libraries, lots of high quality
3rd-party Nginx modules, and most of their external dependencies. It is
designed to help developers easily build scalable web applications, web
services, and dynamic web gateways.


%prep
%setup -q -n %{app}-%{version}
tar -zxf $WORKSPACE/SOURCES/openssl-1.0.2h.tar.gz

#%patch0 -p1


%build
./configure \
    --with-cc-opt="-I%{zlib_prefix}/include -I%{pcre_prefix}/include -I%{openssl_prefix}/include" \
    --with-ld-opt="-L%{zlib_prefix}/lib -L%{pcre_prefix}/lib -L%{openssl_prefix}/lib -Wl,-rpath,%{zlib_prefix}/lib:%{pcre_prefix}/lib:%{openssl_prefix}/lib" \
    --with-pcre-jit \
    --without-http_rds_json_module \
    --without-http_rds_csv_module \
    --without-lua_rds_parser \
    --with-ipv6 \
    --with-stream \
    --with-stream_ssl_module \
    --with-http_v2_module \
    --without-mail_pop3_module \
    --without-mail_imap_module \
    --without-mail_smtp_module \
    --with-http_stub_status_module \
    --with-http_realip_module \
    --with-http_addition_module \
    --with-http_auth_request_module \
    --with-http_secure_link_module \
    --with-http_random_index_module \
    --with-http_gzip_static_module \
    --with-http_sub_module \
    --with-http_dav_module \
    --with-http_flv_module \
    --with-http_mp4_module \
    --with-http_gunzip_module \
    --with-threads \
    --with-file-aio \
    --with-dtrace-probes \
    --with-openssl=openssl-1.0.2h/ \
    --without-luajit-lua52 \
    %{?_smp_mflags}
#    --with-luajit-xcflags='-DLUAJIT_NUMMODE=2 -DLUAJIT_ENABLE_LUA52COMPAT' \

make %{?_smp_mflags}


%install
rm -rf %{buildroot}
make install DESTDIR=%{buildroot}

rm -rf %{buildroot}%{orprefix}/luajit/share/man
rm -rf %{buildroot}%{orprefix}/luajit/lib/libluajit-5.1.a

mkdir -p %{buildroot}/usr/bin
ln -sf %{orprefix}/bin/resty %{buildroot}/usr/bin/
ln -sf %{orprefix}/bin/restydoc %{buildroot}/usr/bin/
ln -sf %{orprefix}/nginx/sbin/nginx %{buildroot}/usr/bin/%{app}

mkdir -p %{buildroot}/etc/init.d
#%{__install} -p -m 0755 %{SOURCE1} %{buildroot}/etc/init.d/%{name}

# to silence the check-rpath error
cp -rf addmodules/* %{buildroot}%{orprefix}/lualib/resty/
export QA_RPATHS=$[ 0x0002 ]


%clean
rm -rf %{buildroot}


#%post
#/sbin/chkconfig --add %{name}


%preun
#if [ $1 -eq 1 ]; then
#    rm -fr /usr/bin/%{app}
#    rm -fr %{orprefix}/luajit/*
#    rm -fr %{orprefix}/lualib/*
#    rm -fr %{orprefix}/nginx/html/*
#    rm -fr %{orprefix}/nginx/logs/
#    rm -fr %{orprefix}/nginx/sbin/*
#    rm -fr %{orprefix}/nginx/tapset/*
#    rm -fr /usr/bin/resty
#    rm -fr %{orprefix}/bin/resty
#    rm -fr /usr/bin/restydoc
#    rm -fr %{orprefix}/bin/restydoc
#    rm -fr %{orprefix}/bin/restydoc-index
#    rm -fr %{orprefix}/bin/md2pod.pl
#    rm -fr %{orprefix}/bin/nginx-xml2pod
#    rm -fr %{orprefix}/pod/*
#    rm -fr %{orprefix}/resty.index
#fi

%files
%defattr(-,root,daemon,-)

#/etc/init.d/%{name}
/usr/bin/%{app}
#%{orprefix}/bin/openresty
#%{orprefix}/site/lualib/
%{orprefix}/luajit/*
%{orprefix}/lualib/*
%{orprefix}/nginx/html/*
%{orprefix}/nginx/logs/
%attr(4755, root, daemon) %{orprefix}/nginx/sbin/*
%{orprefix}/nginx/tapset/*
%config(noreplace) %{orprefix}/nginx/conf/*


# %files resty
# %defattr(-,root,root,-)

/usr/bin/resty
%{orprefix}/bin/resty


# %files doc
# %defattr(-,root,root,-)

/usr/bin/restydoc
%{orprefix}/bin/restydoc
%{orprefix}/bin/restydoc-index
%{orprefix}/bin/md2pod.pl
%{orprefix}/bin/nginx-xml2pod
%{orprefix}/pod/*
%{orprefix}/resty.index

/usr/local/openresty/bin/openresty
/usr/local/openresty/bin/opm
