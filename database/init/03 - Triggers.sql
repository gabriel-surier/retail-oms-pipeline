/****************************************************
* Script name          : Manual script
* Script date          : 28-10-2026 11:41:00
* Database type        : PostgreSQL
* Table name           : outbox
* Request number       : OLTP2
****************************************************/

/****************************************************
* Notify trigger
* Emits a NOTIFY on channel outbox_inserted for each
* inserted row. The payload is the outbox_id.
* The RAISE NOTICE line is for debugging only: remove it
* once the trigger is validated.
****************************************************/

CREATE OR REPLACE FUNCTION oms.fn_outbox_notify()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE NOTICE 'trigger fired, outbox_id=%', NEW.outbox_id;
    PERFORM pg_notify('outbox_inserted', NEW.outbox_id::text);
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_outbox_notify ON oms.outbox;
CREATE TRIGGER trg_outbox_notify
AFTER INSERT ON oms.outbox
FOR EACH ROW
EXECUTE FUNCTION oms.fn_outbox_notify();


/****************************************************
* Insert-only protection
* Blocks UPDATE, DELETE and TRUNCATE on oms.outbox.
* TRUNCATE needs its own statement-level trigger,
* a row-level trigger does not fire on it.
****************************************************/
CREATE OR REPLACE FUNCTION oms.fn_outbox_insert_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'oms.outbox is insert only: % is not allowed', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS trg_outbox_no_update_delete ON oms.outbox;
CREATE TRIGGER trg_outbox_no_update_delete
BEFORE UPDATE OR DELETE ON oms.outbox
FOR EACH ROW
EXECUTE FUNCTION oms.fn_outbox_insert_only();

DROP TRIGGER IF EXISTS trg_outbox_no_truncate ON oms.outbox;
CREATE TRIGGER trg_outbox_no_truncate
BEFORE TRUNCATE ON oms.outbox
FOR EACH STATEMENT
EXECUTE FUNCTION oms.fn_outbox_insert_only();