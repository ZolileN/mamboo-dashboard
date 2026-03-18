DROP TABLE IF EXISTS stores;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS promotions;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS sales_transactions;
DROP TABLE IF EXISTS inventory_snapshots;

CREATE TABLE stores (
    store_id INTEGER PRIMARY KEY,
    store_name TEXT NOT NULL,
    province TEXT NOT NULL,
    city TEXT NOT NULL,
    store_type TEXT NOT NULL,
    opened_date TEXT NOT NULL
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    subcategory TEXT NOT NULL,
    product_name TEXT NOT NULL,
    base_price REAL NOT NULL,
    unit_cost REAL NOT NULL,
    supplier_lead_days INTEGER NOT NULL,
    reorder_point INTEGER NOT NULL
);

CREATE TABLE promotions (
    promotion_id INTEGER PRIMARY KEY,
    promotion_name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    discount_pct REAL NOT NULL,
    category_scope TEXT NOT NULL
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    segment TEXT NOT NULL,
    join_date TEXT NOT NULL,
    home_province TEXT NOT NULL
);

CREATE TABLE sales_transactions (
    transaction_id INTEGER PRIMARY KEY,
    order_date TEXT NOT NULL,
    store_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    customer_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    promotion_id INTEGER,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    unit_cost REAL NOT NULL,
    discount_pct REAL NOT NULL,
    gross_revenue REAL NOT NULL,
    net_revenue REAL NOT NULL,
    gross_profit REAL NOT NULL,
    FOREIGN KEY (store_id) REFERENCES stores(store_id),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (promotion_id) REFERENCES promotions(promotion_id)
);

CREATE TABLE inventory_snapshots (
    snapshot_date TEXT NOT NULL,
    store_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    stock_on_hand INTEGER NOT NULL,
    units_sold_7d INTEGER NOT NULL,
    units_sold_30d INTEGER NOT NULL,
    stockout_flag INTEGER NOT NULL,
    PRIMARY KEY (snapshot_date, store_id, product_id),
    FOREIGN KEY (store_id) REFERENCES stores(store_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
