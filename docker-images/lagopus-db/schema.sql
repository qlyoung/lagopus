USE lagopus;
CREATE TABLE `jobs` (
    `job_id` varchar(128) NOT NULL,
    `driver` varchar(20) NOT NULL,
    `target` varchar(4096) NOT NULL,
    `cores` int(11) NOT NULL,
    `memory` int(11) NOT NULL,
    `deadline` int(11) NOT NULL,
    `create_time` timestamp,
    PRIMARY KEY (`job_id`)
  ) ENGINE=InnoDB;
CREATE TABLE `crashes` (
    `job_id` varchar(128) NOT NULL,
    `type` varchar(64),
    `exploitability` varchar(20),
    `sample_path` varchar(4096) NOT NULL,
    `backtrace` varchar(4096) NOT NULL,
    `backtrace_hash` char(65),  # two md5s plus a period
    PRIMARY KEY (`job_id`, `backtrace_hash`)
  ) ENGINE=InnoDB;

