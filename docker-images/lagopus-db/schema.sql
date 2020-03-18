USE lagopus;
CREATE TABLE `jobs` (
    `job_id` varchar(128) NOT NULL,
    `status` varchar(64) NOT NULL,
    `driver` varchar(32) NOT NULL,
    `target` varchar(4096) NOT NULL,
    `cpus` int(11) NOT NULL,
    `memory` int(11) NOT NULL,
    `deadline` int(11) NOT NULL,
    `create_time` timestamp,
    PRIMARY KEY (`job_id`)
  ) ENGINE=InnoDB;
CREATE TABLE `crashes` (
    `job_id` varchar(128) NOT NULL,
    `type` varchar(64) NOT NULL,
    `is_security_issue` BOOLEAN,
    `is_crash` BOOLEAN,
    `sample_path` varchar(4096) NOT NULL,
    `backtrace` longtext NOT NULL,
    `backtrace_hash` char(65),  # two md5s plus a period
    `return_code` int(11),
    `create_time` timestamp,
    PRIMARY KEY (`job_id`, `backtrace_hash`)
  ) ENGINE=InnoDB;

