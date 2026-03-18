import sqlite3
from pathlib import Path
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "mambo_retail.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

fake = Faker()
random.seed(42)
np.random.seed(42)

PROVINCES = {
    "Gauteng": ["Johannesburg", "Pretoria"],
    "Western Cape": ["Cape Town"],
    "KwaZulu-Natal": ["Durban"],
    "Eastern Cape": ["Gqeberha"],
    "Free State": ["Bloemfontein"],
}

STORES = [
    (1, "Mamboo Sandton", "Gauteng", "Johannesburg", "Flagship", "2019-03-01"),
    (2, "Mamboo Fourways", "Gauteng", "Johannesburg", "Mall", "2020-06-15"),
    (3, "Mamboo Pretoria East", "Gauteng", "Pretoria", "Mall", "2021-02-20"),
    (4, "Mamboo Canal Walk", "Western Cape", "Cape Town", "Flagship", "2018-11-10"),
    (5, "Mamboo Tygervalley", "Western Cape", "Cape Town", "Mall", "2022-04-01"),
    (6, "Mamboo Gateway", "KwaZulu-Natal", "Durban", "Mall", "2019-07-19"),
    (7, "Mamboo Baywest", "Eastern Cape", "Gqeberha", "Community", "2021-09-05"),
    (8, "Mamboo Mimosa", "Free State", "Bloemfontein", "Community", "2023-01-18"),
]

CATEGORY_TREE = {
    "Storage": ["Plastic Bins", "Drawer Units", "Laundry Baskets", "Food Storage"],
    "Cleaning": ["Mops", "Buckets", "Brushes", "Cleaning Accessories"],
    "Kitchenware": ["Bowls", "Jugs", "Utensil Holders", "Lunch Boxes"],
    "Stationery": ["Organisers", "Desk Storage", "Files", "Craft"],
    "Toys": ["Educational", "Outdoor", "Play Storage", "Party"],
}

PROMOTIONS = [
    (1, "Month-End Storage Push", "2025-06-25", "2025-06-30", 0.10, "Storage"),
    (2, "Back to School", "2025-01-10", "2025-01-31", 0.15, "Stationery"),
    (3, "Spring Clean", "2025-09-01", "2025-09-15", 0.12, "Cleaning"),
    (4, "Summer Kitchen Refresh", "2025-11-10", "2025-11-25", 0.08, "Kitchenware"),
]


def create_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def seed_stores(conn):
    conn.executemany(
        "INSERT INTO stores (store_id, store_name, province, city, store_type, opened_date) VALUES (?, ?, ?, ?, ?, ?)",
        STORES,
    )


def seed_products(conn):
    rows = []
    product_id = 1
    for category, subs in CATEGORY_TREE.items():
        for sub in subs:
            for i in range(1, 9):
                base_price = round(np.random.uniform(39, 399), 2)
                cost = round(base_price * np.random.uniform(0.42, 0.68), 2)
                lead = int(np.random.choice([7, 10, 14, 21, 28]))
                reorder = int(np.random.choice([15, 20, 25, 30, 40, 50]))
                name = f"{sub[:-1] if sub.endswith('s') else sub} {i}"
                rows.append(
                    (
                        product_id,
                        f"MB-{category[:3].upper()}-{sub[:3].upper()}-{i:03d}",
                        category,
                        sub,
                        name,
                        base_price,
                        cost,
                        lead,
                        reorder,
                    )
                )
                product_id += 1
    conn.executemany(
        """
        INSERT INTO products
        (product_id, sku, category, subcategory, product_name, base_price, unit_cost, supplier_lead_days, reorder_point)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def seed_promotions(conn):
    conn.executemany(
        "INSERT INTO promotions (promotion_id, promotion_name, start_date, end_date, discount_pct, category_scope) VALUES (?, ?, ?, ?, ?, ?)",
        PROMOTIONS,
    )


def seed_customers(conn, count=1200):
    provinces = list(PROVINCES.keys())
    segments = ["Value", "Family", "Bulk Buyer", "Small Business"]
    rows = []
    start = datetime(2024, 1, 1)
    for cid in range(1, count + 1):
        rows.append(
            (
                cid,
                random.choices(segments, weights=[0.45, 0.3, 0.15, 0.1])[0],
                (start + timedelta(days=random.randint(0, 700))).date().isoformat(),
                random.choice(provinces),
            )
        )
    conn.executemany(
        "INSERT INTO customers (customer_id, segment, join_date, home_province) VALUES (?, ?, ?, ?)",
        rows,
    )


def active_promotion(product_category: str, order_date: datetime):
    for promo in PROMOTIONS:
        _, _, start_date, end_date, discount_pct, scope = promo
        if scope == product_category and pd.Timestamp(start_date) <= pd.Timestamp(order_date.date()) <= pd.Timestamp(end_date):
            return promo[0], discount_pct
    return None, 0.0


def seed_sales(conn):
    products = pd.read_sql_query("SELECT * FROM products", conn)
    stores = pd.read_sql_query("SELECT * FROM stores", conn)
    customers = pd.read_sql_query("SELECT customer_id FROM customers", conn)

    dates = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    rows = []
    tx_id = 1

    category_weights = {
        "Storage": 0.34,
        "Cleaning": 0.22,
        "Kitchenware": 0.18,
        "Stationery": 0.14,
        "Toys": 0.12,
    }
    store_multipliers = {1: 1.35, 2: 1.2, 3: 1.05, 4: 1.28, 5: 1.0, 6: 0.95, 7: 0.8, 8: 0.72}

    for current_date in dates:
        dow = current_date.dayofweek
        month = current_date.month
        seasonal = 1.0
        if month in [1, 11, 12]:
            seasonal += 0.18
        if month in [6, 7]:
            seasonal += 0.08
        if dow in [4, 5]:
            seasonal += 0.16

        for store_id in stores["store_id"]:
            base_orders = int(18 * store_multipliers[store_id] * seasonal)
            orders = max(10, np.random.poisson(base_orders))
            for _ in range(orders):
                channel = random.choices(["In-Store", "Online"], weights=[0.82, 0.18])[0]
                category = random.choices(list(category_weights.keys()), weights=list(category_weights.values()))[0]
                candidates = products[products["category"] == category]
                product = candidates.sample(1).iloc[0]
                quantity = int(random.choices([1, 2, 3, 4, 5, 6], weights=[0.4, 0.24, 0.16, 0.1, 0.06, 0.04])[0])
                promo_id, promo_discount = active_promotion(category, current_date)
                ad_hoc_discount = random.choice([0, 0, 0, 0.05, 0.1]) if quantity >= 4 else 0
                discount = max(promo_discount, ad_hoc_discount)
                unit_price = float(product["base_price"])
                unit_cost = float(product["unit_cost"])
                gross_revenue = round(unit_price * quantity, 2)
                net_revenue = round(gross_revenue * (1 - discount), 2)
                gross_profit = round(net_revenue - (unit_cost * quantity), 2)
                rows.append(
                    (
                        tx_id,
                        current_date.date().isoformat(),
                        int(store_id),
                        channel,
                        int(random.choice(customers["customer_id"])),
                        int(product["product_id"]),
                        promo_id,
                        quantity,
                        unit_price,
                        unit_cost,
                        discount,
                        gross_revenue,
                        net_revenue,
                        gross_profit,
                    )
                )
                tx_id += 1

    conn.executemany(
        """
        INSERT INTO sales_transactions
        (transaction_id, order_date, store_id, channel, customer_id, product_id, promotion_id, quantity, unit_price, unit_cost,
         discount_pct, gross_revenue, net_revenue, gross_profit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def seed_inventory(conn):
    products = pd.read_sql_query("SELECT * FROM products", conn)
    stores = pd.read_sql_query("SELECT * FROM stores", conn)
    sales = pd.read_sql_query(
        "SELECT order_date, store_id, product_id, quantity FROM sales_transactions",
        conn,
        parse_dates=["order_date"],
    )
    sales["order_date"] = pd.to_datetime(sales["order_date"])

    snapshot_dates = pd.date_range("2025-01-31", "2025-12-31", freq="ME")
    rows = []

    for snap_date in snapshot_dates:
        last_7 = sales[(sales["order_date"] <= snap_date) & (sales["order_date"] > snap_date - pd.Timedelta(days=7))]
        last_30 = sales[(sales["order_date"] <= snap_date) & (sales["order_date"] > snap_date - pd.Timedelta(days=30))]
        agg7 = last_7.groupby(["store_id", "product_id"], as_index=False)["quantity"].sum().rename(columns={"quantity": "units_sold_7d"})
        agg30 = last_30.groupby(["store_id", "product_id"], as_index=False)["quantity"].sum().rename(columns={"quantity": "units_sold_30d"})

        for store_id in stores["store_id"]:
            for _, product in products.iterrows():
                units7 = agg7[(agg7["store_id"] == store_id) & (agg7["product_id"] == product["product_id"])]
                units30 = agg30[(agg30["store_id"] == store_id) & (agg30["product_id"] == product["product_id"])]
                units_sold_7d = int(units7["units_sold_7d"].iloc[0]) if not units7.empty else 0
                units_sold_30d = int(units30["units_sold_30d"].iloc[0]) if not units30.empty else 0
                target_stock = max(product["reorder_point"], int(units_sold_30d * np.random.uniform(0.8, 1.6)) + 5)
                stock_on_hand = max(0, int(np.random.normal(target_stock, max(3, target_stock * 0.35))))
                stockout = 1 if stock_on_hand <= max(2, int(product["reorder_point"] * 0.2)) and units_sold_30d > 0 else 0
                rows.append((snap_date.date().isoformat(), int(store_id), int(product["product_id"]), stock_on_hand, units_sold_7d, units_sold_30d, stockout))

    conn.executemany(
        """
        INSERT INTO inventory_snapshots
        (snapshot_date, store_id, product_id, stock_on_hand, units_sold_7d, units_sold_30d, stockout_flag)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def main():
    conn = create_db()
    seed_stores(conn)
    seed_products(conn)
    seed_promotions(conn)
    seed_customers(conn)
    seed_sales(conn)
    seed_inventory(conn)
    conn.commit()
    conn.close()
    print(f"Database created at {DB_PATH}")


if __name__ == "__main__":
    main()
