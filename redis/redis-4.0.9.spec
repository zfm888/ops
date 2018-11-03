%define    _topdir /opt/rpmbuild/rpm/rpmbuild
%define    wmModule redis
Summary:   release package for redis
Name:      yf_%{wmModule}
Version:   4.0.9
Release:   5
License:   GPL
Group:     WM team
Source:    %{wmModule}-%{version}.tar.gz
BuildRoot: %{_topdir}/%{name}-%{version}-%{release}-daemon
Url:       https://redis.io/
Packager:  xxx
Prefix:    %{_prefix}
Prefix:    %{_sysconfdir}
%define    userpath /usr/local/redis
Autoreq: 0

%description
RPM package for user center

%pre
sudo rm %{userpath}/%{wmModule} -rf

%prep
%setup -c

%install
install -d $RPM_BUILD_ROOT%{userpath}
cd %{wmModule}-%{version}
ls
make -j4 PREFIX=$RPM_BUILD_ROOT%{userpath} install

%clean
rm -rf $RPM_BUILD_ROOT
rm -rf $RPM_BUILD_DIR/%{name}-%{version}

%files
%defattr(-,daemon,daemon,-)
%{userpath}

%post
grep '%{userpath}/bin' /etc/profile || echo 'export PATH=$PATH:%{userpath}/bin' >> /etc/profile
