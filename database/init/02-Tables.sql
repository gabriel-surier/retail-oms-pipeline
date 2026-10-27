/****************************************************
* Script name          : Automatic script
* Script date          : 27-10-2026 16:40:57
* Database type        : PostgreSQL
* Table name           : customer
* Request number       : OLTP1
****************************************************/

DROP TABLE IF EXISTS oms.customer;
Create table oms.customer
(
customer_id integer not null,
customer_cd varchar(20),
segment_cd varchar(20),
country_cd varchar(2),
created_ts timestamp,
updated_ts timestamp,
CONSTRAINT customer_PK PRIMARY KEY (customer_id)
);
COMMENT ON COLUMN oms.customer.customer_id IS 'Integer primary key, derived from the source code.';
COMMENT ON COLUMN oms.customer.customer_cd IS 'Source code kept to trace rejects.';
COMMENT ON COLUMN oms.customer.segment_cd IS 'occasional, regular, loyal.';
COMMENT ON COLUMN oms.customer.country_cd IS 'ISO 3166 two-letter code: FR, BE or DE (euro zone).';
COMMENT ON COLUMN oms.customer.created_ts IS 'Customer creation date in the source system, drawn within the simulated period.';
COMMENT ON COLUMN oms.customer.updated_ts IS 'Last modification date in the source system.';


/****************************************************
* Script name          : Automatic script
* Script date          : 27-10-2026 16:40:58
* Database type        : PostgreSQL
* Table name           : product
* Request number       : OLTP1
****************************************************/

DROP TABLE IF EXISTS oms.product;
Create table oms.product
(
product_id integer not null,
product_cd varchar(20),
category_cd varchar(50),
brand_name varchar(50),
product_name varchar(120),
unit_price_amt numeric(10,2),
is_active boolean,
created_ts timestamp,
updated_ts timestamp,
CONSTRAINT product_PK PRIMARY KEY (product_id)
);
COMMENT ON COLUMN oms.product.product_id IS 'Integer primary key, derived from the source code.';
COMMENT ON COLUMN oms.product.product_cd IS 'Product code kept to trace rejects. Format PRD- + 3 digits.';
COMMENT ON COLUMN oms.product.category_cd IS 'English snake_case code: face_care, body_care, fragrance, makeup, wellness.';
COMMENT ON COLUMN oms.product.brand_name IS 'Fictional brand.';
COMMENT ON COLUMN oms.product.product_name IS 'Invented name.';
COMMENT ON COLUMN oms.product.unit_price_amt IS 'Price incl. VAT in euros.';
COMMENT ON COLUMN oms.product.is_active IS 'Allows removing a product without deleting it.';
COMMENT ON COLUMN oms.product.created_ts IS 'Product creation date in the source system.';
COMMENT ON COLUMN oms.product.updated_ts IS 'Last modification date in the source system.';


/****************************************************
* Script name          : Automatic script
* Script date          : 27-10-2026 16:40:59
* Database type        : PostgreSQL
* Table name           : sales_order
* Request number       : OLTP1
****************************************************/

DROP TABLE IF EXISTS oms.sales_order;
Create table oms.sales_order
(
order_id integer not null,
order_cd varchar(20),
customer_id integer,
created_ts timestamp,
updated_ts timestamp,
CONSTRAINT sales_order_PK PRIMARY KEY (order_id)
);
COMMENT ON COLUMN oms.sales_order.order_id IS 'Integer primary key, derived from the source code.';
COMMENT ON COLUMN oms.sales_order.order_cd IS 'Source code kept to trace rejects. Format CMD- + day number (5 digits) + rank within the day (5 digits).';
COMMENT ON COLUMN oms.sales_order.customer_id IS 'References customer.customer_id.';
COMMENT ON COLUMN oms.sales_order.created_ts IS 'Creation date in the source system. ';
COMMENT ON COLUMN oms.sales_order.updated_ts IS 'Last modification date in the source system. Basis of the delta to RAW.';


/****************************************************
* Script name          : Automatic script
* Script date          : 27-10-2026 16:41:00
* Database type        : PostgreSQL
* Table name           : sales_order
* Request number       : OLTP1
****************************************************/

DROP TABLE IF EXISTS oms.sales_order;
Create table oms.sales_order
(
order_id integer not null,
order_cd varchar(20),
customer_id integer,
created_ts timestamp,
updated_ts timestamp,
CONSTRAINT sales_order_PK PRIMARY KEY (order_id)
);
COMMENT ON COLUMN oms.sales_order.order_id IS 'Integer primary key, derived from the source code.';
COMMENT ON COLUMN oms.sales_order.order_cd IS 'Source code kept to trace rejects. Format CMD- + day number (5 digits) + rank within the day (5 digits).';
COMMENT ON COLUMN oms.sales_order.customer_id IS 'References customer.customer_id.';
COMMENT ON COLUMN oms.sales_order.created_ts IS 'Creation date in the source system. ';
COMMENT ON COLUMN oms.sales_order.updated_ts IS 'Last modification date in the source system. Basis of the delta to RAW.';


/****************************************************
* Script name          : Automatic script
* Script date          : 27-10-2026 16:41:01
* Database type        : PostgreSQL
* Table name           : order_line
* Request number       : OLTP1
****************************************************/

DROP TABLE IF EXISTS oms.order_line;
Create table oms.order_line
(
order_line_id bigint not null,
line_cd varchar(20),
order_id integer,
product_id integer not null,
quantity_num integer,
unit_price_amt numeric(10,2),
created_ts timestamp,
updated_ts timestamp,
deleted_ts timestamp,
CONSTRAINT order_line_PK PRIMARY KEY (order_line_id,product_id)
);
COMMENT ON COLUMN oms.order_line.order_line_id IS 'Integer primary key, derived from the source code.';
COMMENT ON COLUMN oms.order_line.line_cd IS 'Source code kept to trace rejects. Format LIG- + 10 digits of the order + line rank (2 digits).';
COMMENT ON COLUMN oms.order_line.order_id IS 'References sales_order.order_id.';
COMMENT ON COLUMN oms.order_line.product_id IS 'References product.product_id.';
COMMENT ON COLUMN oms.order_line.quantity_num IS 'Greater than or equal to 1.';
COMMENT ON COLUMN oms.order_line.unit_price_amt IS 'Price at order time (copy, no computation).';
COMMENT ON COLUMN oms.order_line.created_ts IS 'Line creation date in the source system.';
COMMENT ON COLUMN oms.order_line.updated_ts IS 'Last modification date in the source system. Basis of the delta to RAW.';
COMMENT ON COLUMN oms.order_line.deleted_ts IS 'Logical deletion date. NULL = active row. Never a physical DELETE.';


/****************************************************
* Script name          : Automatic script
* Script date          : 27-10-2026 16:41:02
* Database type        : PostgreSQL
* Table name           : outbox
* Request number       : OLTP1
****************************************************/

DROP TABLE IF EXISTS oms.outbox;
Create table oms.outbox
(
outbox_id bigint not null,
event_id bigint,
event_cd varchar(20),
delivery_num integer,
order_id integer not null,
customer_id integer not null,
status_cd varchar(20),
event_ts timestamp,
CONSTRAINT outbox_PK PRIMARY KEY (outbox_id,order_id,customer_id)
);
COMMENT ON COLUMN oms.outbox.outbox_id IS 'Technical key of the outbox. Several rows may share one event_cd (simulated duplicate). Insert-only table.';
COMMENT ON COLUMN oms.outbox.event_id IS 'Integer identifier of the transition, derived from the source code. Same for both deliveries of a duplicate.';
COMMENT ON COLUMN oms.outbox.event_cd IS 'Source code kept to trace rejects. Format EVT- + 10 digits of the order + status code (1 created, 2 paid, 3 shipped, 4 delivered, 5 cancelled).';
COMMENT ON COLUMN oms.outbox.delivery_num IS 'Delivery number: 1, or 2 for the simulated duplicate (1 % of events). Replaying the same entry (same event_cd and same delivery_num) is ignored.';
COMMENT ON COLUMN oms.outbox.order_id IS 'References sales_order.order_id.';
COMMENT ON COLUMN oms.outbox.customer_id IS 'References customer.customer_id. Carried by the message.';
COMMENT ON COLUMN oms.outbox.status_cd IS 'created, paid, shipped, delivered, cancelled.';
COMMENT ON COLUMN oms.outbox.event_ts IS 'Simulated transition date. Used for status ordering.';


/****************************************************
* Script name          : Automatic script
* Script date          : 27-10-2026 16:41:03
* Database type        : PostgreSQL
* Table name           : publish_checkpoint
* Request number       : OLTP1
****************************************************/

DROP TABLE IF EXISTS ops.publish_checkpoint;
Create table ops.publish_checkpoint
(
last_outbox_id bigint not null,
tec_load_ts timestamp,
CONSTRAINT publish_checkpoint_PK PRIMARY KEY (last_outbox_id)
);
COMMENT ON COLUMN ops.publish_checkpoint.last_outbox_id IS 'publish_checkpoint';
COMMENT ON COLUMN ops.publish_checkpoint.tec_load_ts IS 'publish_checkpoint';
