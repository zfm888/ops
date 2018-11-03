/*********************************************
MySQL运维工具库
*********************************************/
CREATE DATABASE oputil;

/*********************************************
pt-heartbeat监控复制延迟
*********************************************/
CREATE TABLE oputil.heartbeat (
    ts                    varchar(26)  NOT NULL,
    server_id             int unsigned NOT NULL PRIMARY KEY,
    file                  varchar(255) DEFAULT NULL,    -- SHOW MASTER STATUS
    position              bigint unsigned DEFAULT NULL, -- SHOW MASTER STATUS
    relay_master_log_file varchar(255) DEFAULT NULL,    -- SHOW SLAVE STATUS
    exec_master_log_pos   bigint unsigned DEFAULT NULL  -- SHOW SLAVE STATUS
) ENGINE=InnoDB DEFAULT CHARSET=UTF8;

-- On Master
-- SHELL> pt-heartbeat --daemonize -D oputil --update -h localhost --user monitor --ask-pass

-- On Slave
-- SHELL> pt-heartbeat -D oputil -h localhost --master-server-id xxxx --user monitor --ask-pass --monitor
-- SHELL> pt-heartbeat -D oputil -h localhost --master-server-id xxxx --user monitor --ask-pass --check
