-- Schemas initialization
CREATE SCHEMA IF NOT EXISTS oms;
COMMENT ON SCHEMA oms IS 'OMS source data';
CREATE SCHEMA IF NOT EXISTS ops;
COMMENT ON SCHEMA ops IS 'Operations layer';