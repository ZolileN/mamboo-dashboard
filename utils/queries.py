from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / 'mambo_retail.db'


def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def run_query(query: str) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(query, conn)


def load_sales() -> pd.DataFrame:
    df = run_query(
        """
        SELECT
            s.transaction_id,
            s.order_date,
            s.channel,
            s.quantity,
            s.unit_price,
            s.unit_cost,
            s.discount_pct,
            s.gross_revenue,
            s.net_revenue,
            s.gross_profit,
            s.promotion_id,
            st.store_id,
            st.store_name,
            st.province,
            st.city,
            st.store_type,
            p.product_id,
            p.category,
            p.subcategory,
            p.product_name,
            p.sku,
            p.reorder_point,
            p.supplier_lead_days,
            c.segment AS customer_segment,
            pr.promotion_name
        FROM sales_transactions s
        JOIN stores st ON s.store_id = st.store_id
        JOIN products p ON s.product_id = p.product_id
        LEFT JOIN customers c ON s.customer_id = c.customer_id
        LEFT JOIN promotions pr ON s.promotion_id = pr.promotion_id
        """
    )
    df['order_date'] = pd.to_datetime(df['order_date'])
    df['year_month'] = df['order_date'].dt.to_period('M').astype(str)
    df['is_discounted'] = df['discount_pct'] > 0
    df['margin_pct'] = (df['gross_profit'] / df['net_revenue']).fillna(0)
    df['avg_selling_price'] = (df['net_revenue'] / df['quantity']).fillna(0)
    return df


def load_inventory() -> pd.DataFrame:
    df = run_query(
        """
        SELECT
            i.snapshot_date,
            i.stock_on_hand,
            i.units_sold_7d,
            i.units_sold_30d,
            i.stockout_flag,
            st.store_id,
            st.store_name,
            st.province,
            st.city,
            p.product_id,
            p.category,
            p.subcategory,
            p.product_name,
            p.sku,
            p.reorder_point,
            p.supplier_lead_days,
            p.unit_cost
        FROM inventory_snapshots i
        JOIN stores st ON i.store_id = st.store_id
        JOIN products p ON i.product_id = p.product_id
        """
    )
    df['snapshot_date'] = pd.to_datetime(df['snapshot_date'])
    daily_velocity = (df['units_sold_30d'] / 30).replace(0, pd.NA)
    df['cover_days'] = (df['stock_on_hand'] / daily_velocity).fillna(999)
    df['inventory_value_cost'] = df['stock_on_hand'] * df['unit_cost']
    return df


def load_store_dimension() -> pd.DataFrame:
    return run_query('SELECT * FROM stores')
