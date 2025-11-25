-- db_init_fixed.sql  (MySQL 8/9 compatible)
CREATE DATABASE IF NOT EXISTS cyberdefense CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE cyberdefense;

-- Users table (store bcrypt full hash; no separate salt column required)
CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(150) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  email VARCHAR(255) DEFAULT NULL,
  role ENUM('admin','user') DEFAULT 'user',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Alerts table: detections sent to dashboard
CREATE TABLE IF NOT EXISTS alerts (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  model VARCHAR(128) NOT NULL,
  prob DOUBLE NOT NULL,
  label VARCHAR(64) DEFAULT NULL,
  src_ip VARCHAR(45) DEFAULT NULL,
  dst_ip VARCHAR(45) DEFAULT NULL,
  meta JSON NULL,
  processed TINYINT(1) DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_alerts_created_at (created_at),
  INDEX idx_alerts_model (model),
  INDEX idx_alerts_processed (processed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Raw mouse events table (keeps original raw JSON).
-- NOTE: changed UNIQUE -> INDEX so multiple raw batches per session are allowed.
CREATE TABLE IF NOT EXISTS mouse_raw (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(128) NOT NULL,
  events JSON NOT NULL,
  meta JSON NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_mouse_raw_session_id (session_id),
  INDEX idx_mouse_raw_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mouse dynamics (derived features + label/prediction) - JSON-style table:
CREATE TABLE IF NOT EXISTS mouse_dynamics (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(128) NOT NULL,
  user_id INT DEFAULT NULL,
  features JSON NOT NULL,               -- derived features: avg_speed, std_speed, avg_acc, curvature...
  raw_events JSON NULL,
  label ENUM('human','bot','unknown') DEFAULT 'unknown',
  predicted_label VARCHAR(32) DEFAULT NULL,
  model VARCHAR(64) DEFAULT NULL,       -- which model produced prediction
  score DOUBLE DEFAULT NULL,            -- model score/confidence
  meta JSON NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_mouse_dyn_session (session_id),
  INDEX idx_mouse_dyn_user (user_id),
  INDEX idx_mouse_dyn_created (created_at),
  CONSTRAINT fk_mousedyn_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Traffic logs / packet-level features (flow or packet features)
CREATE TABLE IF NOT EXISTS traffic_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  features JSON NOT NULL,               -- packet/flow-level features JSON
  prob DOUBLE DEFAULT NULL,             -- detection score
  label VARCHAR(32) DEFAULT NULL,       -- true label if available
  predicted_label VARCHAR(32) DEFAULT NULL,
  src_ip VARCHAR(45) DEFAULT NULL,
  dst_ip VARCHAR(45) DEFAULT NULL,
  src_port INT NULL,
  dst_port INT NULL,
  proto VARCHAR(16) DEFAULT NULL,
  meta JSON NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_traffic_created (created_at),
  INDEX idx_traffic_srcdst (src_ip, dst_ip)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Flow records (kept for compatibility if used by other parts)
CREATE TABLE IF NOT EXISTS flow_records (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  features JSON NOT NULL,
  prob DOUBLE DEFAULT NULL,
  label VARCHAR(32) DEFAULT NULL,
  predicted_label VARCHAR(32) DEFAULT NULL,
  src_ip VARCHAR(45) DEFAULT NULL,
  dst_ip VARCHAR(45) DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_flow_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Detailed per-session / aggregated mouse metrics (renamed to mouse_dynamics_summary to avoid duplicate name)
-- This stores extracted numeric columns
CREATE TABLE IF NOT EXISTS mouse_dynamics_summary (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(128) NOT NULL,
  page VARCHAR(255),
  ts BIGINT NOT NULL, 
  count INT,
  avg_velocity DOUBLE,
  median_velocity DOUBLE,
  max_velocity DOUBLE,
  avg_acc DOUBLE,
  max_acc DOUBLE,
  std_acc DOUBLE,
  curvature_mean DOUBLE,
  curvature_std DOUBLE,
  pause_count INT,
  longest_pause INT,
  pct_pause_time DOUBLE,
  path_length DOUBLE,
  euclidean_distance DOUBLE,
  tortuosity DOUBLE,
  smoothness_index DOUBLE,
  mean_angle DOUBLE,
  angle_std DOUBLE,
  click_count INT,
  avg_dwell_before_click DOUBLE,
  avg_time_between_clicks DOUBLE,
  click_speed DOUBLE,
  meta JSON NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_mouse_dynamics_summary_session (session_id),
  INDEX idx_mouse_dynamics_summary_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;