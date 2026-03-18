from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.queries import load_inventory, load_sales, load_store_dimension

BASE_DIR = Path(__file__).resolve().parent

st.set_page_config(
    page_title='Mamboo Retail Intelligence Dashboard',
    page_icon='📦',
    layout='wide',
    initial_sidebar_state='expanded',
)


def inject_css() -> None:
    css_path = BASE_DIR / 'assets' / 'style.css'
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def get_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return load_sales(), load_inventory(), load_store_dimension()


def fmt_currency(value: float) -> str:
    return f"R {value:,.0f}"


def fmt_pct(value: float) -> str:
    return f"{value:.1%}"


def fmt_delta(current: float, previous: float, kind: str = 'pct') -> str:
    if previous == 0:
        return 'n/a'
    delta = (current - previous) / previous if kind == 'pct' else current - previous
    sign = '+' if delta >= 0 else ''
    return f"{sign}{delta:.1%}" if kind == 'pct' else f"{sign}{delta:,.0f}"


@st.cache_data(show_spinner=False)
def filter_data(
    sales: pd.DataFrame,
    inventory: pd.DataFrame,
    start_date,
    end_date,
    provinces: list[str],
    categories: list[str],
    channels: list[str],
    segments: list[str],
):
    sales_f = sales[(sales['order_date'].dt.date >= start_date) & (sales['order_date'].dt.date <= end_date)].copy()
    inv_f = inventory[(inventory['snapshot_date'].dt.date >= start_date) & (inventory['snapshot_date'].dt.date <= end_date)].copy()

    if provinces:
        sales_f = sales_f[sales_f['province'].isin(provinces)]
        inv_f = inv_f[inv_f['province'].isin(provinces)]
    if categories:
        sales_f = sales_f[sales_f['category'].isin(categories)]
        inv_f = inv_f[inv_f['category'].isin(categories)]
    if channels:
        sales_f = sales_f[sales_f['channel'].isin(channels)]
    if segments:
        sales_f = sales_f[sales_f['customer_segment'].isin(segments)]

    return sales_f, inv_f


@st.cache_data(show_spinner=False)
def compute_summary(sales_f: pd.DataFrame, inv_f: pd.DataFrame) -> dict[str, float]:
    revenue = float(sales_f['net_revenue'].sum())
    profit = float(sales_f['gross_profit'].sum())
    orders = int(sales_f['transaction_id'].nunique())
    units = int(sales_f['quantity'].sum())
    avg_basket = revenue / orders if orders else 0
    margin = profit / revenue if revenue else 0
    discounted_mix = float(sales_f['is_discounted'].mean()) if not sales_f.empty else 0

    if inv_f.empty:
        stockout_rate = 0
        sell_through = 0
        inventory_value = 0
        low_cover_share = 0
    else:
        stockout_rate = float(inv_f['stockout_flag'].mean())
        denom = inv_f['units_sold_30d'].sum() + inv_f['stock_on_hand'].sum()
        sell_through = float(inv_f['units_sold_30d'].sum() / denom) if denom else 0
        inventory_value = float(inv_f['inventory_value_cost'].sum())
        low_cover_share = float((inv_f['cover_days'] < 14).mean())

    return {
        'revenue': revenue,
        'profit': profit,
        'orders': orders,
        'units': units,
        'avg_basket': avg_basket,
        'margin': margin,
        'discounted_mix': discounted_mix,
        'stockout_rate': stockout_rate,
        'sell_through': sell_through,
        'inventory_value': inventory_value,
        'low_cover_share': low_cover_share,
    }


@st.cache_data(show_spinner=False)
def compute_comparison_window(
    sales: pd.DataFrame,
    inventory: pd.DataFrame,
    start_date,
    end_date,
    provinces: list[str],
    categories: list[str],
    channels: list[str],
    segments: list[str],
) -> dict[str, float]:
    days = max((end_date - start_date).days + 1, 1)
    prev_end = start_date - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=days - 1)
    sales_prev, inv_prev = filter_data(
        sales,
        inventory,
        prev_start,
        prev_end,
        provinces,
        categories,
        channels,
        segments,
    )
    return compute_summary(sales_prev, inv_prev)


@st.cache_data(show_spinner=False)
def build_transfer_view(inv_f: pd.DataFrame) -> pd.DataFrame:
    latest_inventory = inv_f[inv_f['snapshot_date'] == inv_f['snapshot_date'].max()].copy()
    if latest_inventory.empty:
        return pd.DataFrame()

    latest_inventory['need_flag'] = (latest_inventory['cover_days'] < 7) | (latest_inventory['stock_on_hand'] <= latest_inventory['reorder_point'])
    latest_inventory['excess_flag'] = latest_inventory['cover_days'] > 45

    needy = latest_inventory[latest_inventory['need_flag']].copy()
    excess = latest_inventory[latest_inventory['excess_flag']].copy()
    if needy.empty or excess.empty:
        return pd.DataFrame()

    needy = needy[['sku', 'product_name', 'category', 'store_name', 'cover_days', 'stock_on_hand', 'reorder_point']].rename(
        columns={'store_name': 'destination_store', 'cover_days': 'destination_cover_days', 'stock_on_hand': 'destination_stock'}
    )
    excess = excess[['sku', 'store_name', 'cover_days', 'stock_on_hand']].rename(
        columns={'store_name': 'source_store', 'cover_days': 'source_cover_days', 'stock_on_hand': 'source_stock'}
    )

    transfer = needy.merge(excess, on='sku', how='inner')
    transfer = transfer[transfer['source_store'] != transfer['destination_store']].copy()
    transfer['suggested_transfer_units'] = (
        (transfer['source_stock'] * 0.2).clip(lower=3).round().astype(int)
    )
    transfer['priority_score'] = (
        (7 - transfer['destination_cover_days']).clip(lower=0) * 0.6
        + (transfer['source_cover_days'] / 60).clip(upper=1) * 0.4
    )
    return transfer.sort_values(['priority_score', 'destination_cover_days'], ascending=[False, True])


def add_layout_defaults(fig, title: str | None = None):
    fig.update_layout(
        title=title,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=20, r=20, t=60, b=20),
        legend_title_text='',
        hoverlabel=dict(bgcolor='#0f172a'),
    )
    return fig


def render_panel(title: str, subtitle: str, label: str = 'Decision lens') -> None:
    st.markdown(
        f"""
        <div class='hero-card'>
            <div class='section-label'>{label}</div>
            <div class='hero-title' style='font-size:1.1rem'>{title}</div>
            <div class='hero-subtitle'>{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_insight_card(title: str, body: str, label: str = 'Insight') -> None:
    st.markdown(
        f"""
        <div class='insight-card'>
            <div class='section-label'>{label}</div>
            <div class='insight-title'>{title}</div>
            <div class='insight-body'>{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_filter_summary(start_date, end_date, provinces, categories, channels, segments) -> None:
    items = [
        f"<span class='filter-pill'>Window: {start_date} → {end_date}</span>",
        f"<span class='filter-pill'>Province: {', '.join(provinces) if provinces else 'All'}</span>",
        f"<span class='filter-pill'>Category: {', '.join(categories) if categories else 'All'}</span>",
        f"<span class='filter-pill'>Channel: {', '.join(channels) if channels else 'All'}</span>",
        f"<span class='filter-pill'>Segment: {', '.join(segments) if segments else 'All'}</span>",
    ]
    st.markdown(f"<div class='pill-row'>{''.join(items)}</div>", unsafe_allow_html=True)


def executive_page(sales_f: pd.DataFrame, inv_f: pd.DataFrame, summary: dict[str, float]) -> None:
    render_panel(
        'What is driving the business right now?',
        'This view blends top-line performance, category mix, and store concentration to help frame the commercial story before moving into operational detail.',
    )
    left, right = st.columns([1.65, 1])

    with left:
        monthly = sales_f.groupby('year_month', as_index=False)[['net_revenue', 'gross_profit']].sum()
        fig = px.line(monthly, x='year_month', y=['net_revenue', 'gross_profit'], markers=True)
        fig = add_layout_defaults(fig, 'Revenue and Gross Profit Trend')
        st.plotly_chart(fig, use_container_width=True)

        cat = (
            sales_f.groupby('category', as_index=False)[['net_revenue', 'gross_profit', 'quantity']]
            .sum()
            .sort_values('net_revenue', ascending=False)
        )
        fig = px.bar(cat, x='category', y='net_revenue', color='gross_profit', text_auto='.2s')
        fig = add_layout_defaults(fig, 'Category Revenue Contribution')
        st.plotly_chart(fig, use_container_width=True)

    with right:
        store_rank = sales_f.groupby('store_name', as_index=False)['net_revenue'].sum().sort_values('net_revenue', ascending=True)
        fig = px.bar(store_rank.tail(8), x='net_revenue', y='store_name', orientation='h')
        fig = add_layout_defaults(fig, 'Top Stores by Revenue')
        st.plotly_chart(fig, use_container_width=True)

        latest_inventory = inv_f[inv_f['snapshot_date'] == inv_f['snapshot_date'].max()].copy()
        if not latest_inventory.empty:
            movers = latest_inventory.groupby('category', as_index=False)[['stock_on_hand', 'units_sold_30d']].sum()
            movers['inventory_cover_days'] = movers['stock_on_hand'] / (movers['units_sold_30d'] / 30).replace(0, 1)
            fig = px.bar(movers.sort_values('inventory_cover_days', ascending=False), x='category', y='inventory_cover_days', text_auto='.1f')
            fig = add_layout_defaults(fig, 'Inventory Cover by Category')
            st.plotly_chart(fig, use_container_width=True)

        render_insight_card(
            'Commercial readout',
            (
                f"Revenue stands at <b>{fmt_currency(summary['revenue'])}</b> with gross margin at "
                f"<b>{fmt_pct(summary['margin'])}</b>. Discounted transactions represent "
                f"<b>{fmt_pct(summary['discounted_mix'])}</b> of the mix, which is useful for discussing trade-offs between volume and margin."
            ),
            'Executive'
        )


def store_page(sales_f: pd.DataFrame, inv_f: pd.DataFrame) -> None:
    render_panel(
        'Which branches need intervention?',
        'Read revenue, margin, and stockout pressure together. The aim is to separate low-demand stores from availability-constrained stores.',
        'Operations lens',
    )
    store_perf = sales_f.groupby(['store_name', 'province', 'city', 'store_type'], as_index=False)[['net_revenue', 'gross_profit', 'quantity']].sum()
    store_perf['margin_pct'] = (store_perf['gross_profit'] / store_perf['net_revenue']).fillna(0)
    inv_store = inv_f.groupby('store_name', as_index=False)['stockout_flag'].mean().rename(columns={'stockout_flag': 'stockout_rate'})
    store_perf = store_perf.merge(inv_store, on='store_name', how='left')
    store_perf['revenue_per_unit'] = (store_perf['net_revenue'] / store_perf['quantity']).fillna(0)

    c1, c2 = st.columns([1.2, 1])
    with c1:
        fig = px.scatter(
            store_perf,
            x='net_revenue',
            y='margin_pct',
            size='quantity',
            color='province',
            hover_name='store_name',
            custom_data=['stockout_rate', 'store_type'],
        )
        fig.update_traces(
            hovertemplate='<b>%{hovertext}</b><br>Revenue: R %{x:,.0f}<br>Margin: %{y:.1%}<br>Units: %{marker.size:,.0f}<br>Stockout rate: %{customdata[0]:.1%}<br>Type: %{customdata[1]}<extra></extra>'
        )
        fig = add_layout_defaults(fig, 'Store Revenue vs Margin')
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(store_perf.sort_values('net_revenue', ascending=False), x='store_name', y='net_revenue', color='province', text_auto='.2s')
        fig = add_layout_defaults(fig, 'Store Revenue Ranking')
        st.plotly_chart(fig, use_container_width=True)

    under_pressure = store_perf[(store_perf['stockout_rate'] > store_perf['stockout_rate'].median()) & (store_perf['net_revenue'] > store_perf['net_revenue'].median())]
    label = ', '.join(under_pressure['store_name'].tolist()[:3]) if not under_pressure.empty else 'No major pressure points in current filter range'
    render_insight_card(
        'Stores needing stock intervention',
        f"High-revenue stores with elevated stockout pressure: <b>{label}</b>. These are strong candidates for transfer logic or tighter reorder thresholds.",
        'Operations',
    )

    display = store_perf.sort_values('net_revenue', ascending=False).assign(
        net_revenue=lambda d: d['net_revenue'].map(fmt_currency),
        gross_profit=lambda d: d['gross_profit'].map(fmt_currency),
        margin_pct=lambda d: (d['margin_pct'] * 100).round(1).astype(str) + '%',
        stockout_rate=lambda d: (d['stockout_rate'] * 100).round(1).astype(str) + '%',
        revenue_per_unit=lambda d: d['revenue_per_unit'].round(2),
    )
    st.dataframe(display, use_container_width=True, hide_index=True)


def category_page(sales_f: pd.DataFrame) -> None:
    render_panel(
        'How concentrated is the assortment?',
        'This page highlights hero categories, high-volume/low-margin SKUs, and assortment concentration using a simple ABC logic.',
        'Merchandising lens',
    )
    cat = sales_f.groupby(['category', 'subcategory'], as_index=False)[['net_revenue', 'gross_profit', 'quantity']].sum()
    cat['margin_pct'] = (cat['gross_profit'] / cat['net_revenue']).fillna(0)
    fig = px.treemap(cat, path=['category', 'subcategory'], values='net_revenue', color='margin_pct')
    fig = add_layout_defaults(fig, 'Category and Subcategory Mix')
    st.plotly_chart(fig, use_container_width=True)

    sku = sales_f.groupby(['sku', 'product_name', 'category'], as_index=False)[['net_revenue', 'gross_profit', 'quantity']].sum()
    sku['margin_pct'] = (sku['gross_profit'] / sku['net_revenue']).fillna(0)
    fig = px.scatter(sku, x='quantity', y='margin_pct', size='net_revenue', color='category', hover_name='product_name')
    fig = add_layout_defaults(fig, 'SKU Volume vs Margin')
    st.plotly_chart(fig, use_container_width=True)

    sku = sku.sort_values('net_revenue', ascending=False).reset_index(drop=True)
    sku['revenue_share'] = sku['net_revenue'] / sku['net_revenue'].sum()
    sku['cum_share'] = sku['revenue_share'].cumsum()
    sku['abc_class'] = pd.cut(sku['cum_share'], bins=[0, 0.8, 0.95, 1.0], labels=['A', 'B', 'C'], include_lowest=True)

    a_share = (sku['abc_class'] == 'A').mean()
    render_insight_card(
        'Assortment concentration',
        f"About <b>{fmt_pct(a_share)}</b> of SKUs drive roughly 80% of revenue in the current slice. This is a useful storyline for hero-SKU protection and tail rationalisation.",
        'Merchandising',
    )

    t1, t2 = st.columns(2)
    with t1:
        st.subheader('Top 20 SKUs')
        st.dataframe(sku[['sku', 'product_name', 'category', 'net_revenue', 'gross_profit', 'quantity', 'abc_class']].head(20), use_container_width=True, hide_index=True)
    with t2:
        st.subheader('Bottom 20 SKUs')
        st.dataframe(sku[['sku', 'product_name', 'category', 'net_revenue', 'gross_profit', 'quantity', 'abc_class']].sort_values('net_revenue').head(20), use_container_width=True, hide_index=True)


def inventory_page(inv_f: pd.DataFrame) -> None:
    render_panel(
        'Where is stock either too thin or too heavy?',
        'Inventory health is framed around cover days, stockout risk, and a basic replenishment queue built from demand and lead time.',
        'Inventory lens',
    )
    latest_inventory = inv_f[inv_f['snapshot_date'] == inv_f['snapshot_date'].max()].copy()
    latest_inventory['inventory_status'] = pd.cut(
        latest_inventory['cover_days'],
        bins=[-1, 7, 30, 60, 9999],
        labels=['Critical', 'Healthy', 'Overstocked', 'Excess'],
    )

    c1, c2 = st.columns([1, 1.1])
    with c1:
        fig = px.histogram(latest_inventory, x='inventory_status', color='inventory_status')
        fig = add_layout_defaults(fig, 'Inventory Status Distribution')
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        stockout_view = latest_inventory.groupby(['store_name', 'category'], as_index=False)['stockout_flag'].mean()
        fig = px.density_heatmap(stockout_view, x='store_name', y='category', z='stockout_flag')
        fig = add_layout_defaults(fig, 'Stockout Heatmap by Store and Category')
        st.plotly_chart(fig, use_container_width=True)

    latest_inventory['lost_sales_proxy'] = latest_inventory.apply(
        lambda r: (max(r['units_sold_30d'] / 30, 0) * max(r['supplier_lead_days'], 1)) if r['stockout_flag'] == 1 else 0,
        axis=1,
    )
    repl = latest_inventory[[
        'store_name', 'category', 'sku', 'product_name', 'stock_on_hand', 'units_sold_30d',
        'reorder_point', 'cover_days', 'supplier_lead_days', 'lost_sales_proxy', 'inventory_value_cost'
    ]]
    repl = repl[(repl['stock_on_hand'] <= repl['reorder_point']) | (repl['cover_days'] < 7)]
    repl = repl.sort_values(['cover_days', 'lost_sales_proxy'], ascending=[True, False])

    render_insight_card(
        'Replenishment priority',
        'Cover days, reorder points, and a simple lead-time lost-sales proxy surface where intervention is most commercially urgent.',
        'Inventory',
    )
    st.dataframe(repl.head(30), use_container_width=True, hide_index=True)
    st.download_button(
        'Download replenishment queue as CSV',
        data=repl.to_csv(index=False).encode('utf-8'),
        file_name='mamboo_replenishment_queue.csv',
        mime='text/csv',
    )


def promo_page(sales_f: pd.DataFrame) -> None:
    render_panel(
        'Is discounting helping or leaking margin?',
        'This page looks at discount bands and campaign tags through a profit lens rather than pure volume.',
        'Pricing lens',
    )
    discount_perf = sales_f.copy()
    discount_perf['discount_band'] = pd.cut(
        discount_perf['discount_pct'],
        bins=[-0.001, 0.0, 0.05, 0.10, 0.20],
        labels=['No Discount', '0-5%', '5-10%', '10-20%'],
    )

    c1, c2 = st.columns(2)
    with c1:
        band_summary = discount_perf.groupby('discount_band', as_index=False, observed=False)[['net_revenue', 'gross_profit', 'quantity']].sum()
        fig = px.bar(band_summary, x='discount_band', y=['net_revenue', 'gross_profit'], barmode='group')
        fig = add_layout_defaults(fig, 'Revenue and Profit by Discount Band')
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        promo_cat = discount_perf.groupby(['category', 'discount_band'], as_index=False, observed=False)['quantity'].sum()
        fig = px.bar(promo_cat, x='category', y='quantity', color='discount_band')
        fig = add_layout_defaults(fig, 'Units Sold by Category and Discount Band')
        st.plotly_chart(fig, use_container_width=True)

    promo_table = discount_perf.groupby(['promotion_name'], dropna=False, as_index=False)[['net_revenue', 'gross_profit', 'quantity']].sum()
    promo_table['promotion_name'] = promo_table['promotion_name'].fillna('No campaign tag')
    promo_table['margin_pct'] = (promo_table['gross_profit'] / promo_table['net_revenue']).fillna(0)
    st.subheader('Promotion summary')
    st.dataframe(promo_table.sort_values('net_revenue', ascending=False), use_container_width=True, hide_index=True)


def opportunity_page(sales_f: pd.DataFrame, inv_f: pd.DataFrame) -> None:
    render_panel(
        'What should a branch manager act on first?',
        'The queue below blends demand, profitability, stock cover, and stockout pressure into a lightweight prioritisation model.',
        'Decision support',
    )
    latest_inventory = inv_f[inv_f['snapshot_date'] == inv_f['snapshot_date'].max()].copy()
    sku_sales = sales_f.groupby(['store_name', 'sku', 'product_name', 'category'], as_index=False)[['net_revenue', 'quantity', 'gross_profit']].sum()
    sku_inv = latest_inventory.groupby(['store_name', 'sku', 'product_name', 'category'], as_index=False)[['stock_on_hand', 'cover_days', 'stockout_flag']].mean()
    merged = sku_sales.merge(sku_inv, on=['store_name', 'sku', 'product_name', 'category'], how='left')
    merged['opportunity_score'] = (
        merged['net_revenue'].rank(pct=True) * 0.45
        + merged['gross_profit'].rank(pct=True) * 0.25
        + (1 - merged['cover_days'].clip(upper=90).fillna(90) / 90) * 0.2
        + merged['stockout_flag'].fillna(0) * 0.1
    )
    merged = merged.sort_values('opportunity_score', ascending=False)

    fig = go.Figure(
        go.Indicator(
            mode='gauge+number',
            value=float((merged['stockout_flag'].fillna(0).mean()) * 100),
            title={'text': 'Current Stockout Pressure Index'},
            gauge={'axis': {'range': [0, 100]}},
        )
    )
    fig = add_layout_defaults(fig)
    st.plotly_chart(fig, use_container_width=True)

    transfer = build_transfer_view(inv_f)
    if not transfer.empty:
        render_insight_card(
            'Inter-store transfer opportunities',
            'Potential transfers appear where one branch shows excess cover while another faces low cover on the same SKU. This is a strong interview talking point because it links merchandising and supply chain decisions.',
            'Action',
        )
        st.dataframe(
            transfer[['sku', 'product_name', 'category', 'source_store', 'destination_store', 'source_cover_days', 'destination_cover_days', 'suggested_transfer_units']].head(20),
            use_container_width=True,
            hide_index=True,
        )

    st.subheader('Priority queue')
    st.dataframe(
        merged[['store_name', 'sku', 'product_name', 'category', 'net_revenue', 'gross_profit', 'quantity', 'stock_on_hand', 'cover_days', 'stockout_flag', 'opportunity_score']].head(25),
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        'Download opportunity queue as CSV',
        data=merged.to_csv(index=False).encode('utf-8'),
        file_name='mamboo_opportunity_queue.csv',
        mime='text/csv',
    )


def business_recommendations_page(sales_f: pd.DataFrame, inv_f: pd.DataFrame, summary: dict[str, float]) -> None:
    render_panel(
        'What actions should management take next?',
        'Recommendations are generated from the current filtered slice and prioritised around revenue risk, inventory efficiency, pricing discipline, and store execution.',
        'Business recommendations',
    )

    latest_inventory = inv_f[inv_f['snapshot_date'] == inv_f['snapshot_date'].max()].copy()
    recs: list[dict[str, str | float]] = []

    if not latest_inventory.empty:
        critical = latest_inventory[latest_inventory['cover_days'] < 7].copy()
        if not critical.empty:
            critical_value = float(critical['inventory_value_cost'].sum())
            stockout_share = float((critical['stockout_flag'] == 1).mean()) if 'stockout_flag' in critical else 0
            recs.append({
                'priority': 1,
                'theme': 'Inventory replenishment',
                'recommendation': 'Replenish critical low-cover SKUs before the next supplier lead-time window closes.',
                'why_it_matters': f"{len(critical):,} SKU-store positions are below 7 cover days, putting roughly {fmt_currency(critical_value)} of working assortment at risk.",
                'evidence': f"Critical cover share: {len(critical)/len(latest_inventory):.1%} | Stockout presence inside critical pool: {stockout_share:.1%}",
                'owner': 'Supply chain / planning',
            })

        excess = latest_inventory[latest_inventory['cover_days'] > 60].copy()
        if not excess.empty:
            excess_value = float(excess['inventory_value_cost'].sum())
            recs.append({
                'priority': 2,
                'theme': 'Inventory efficiency',
                'recommendation': 'Reduce excess cover on slow-moving SKUs through transfers, markdowns, or smaller future buys.',
                'why_it_matters': f"{len(excess):,} SKU-store positions sit above 60 cover days, tying up about {fmt_currency(excess_value)} in stock cost.",
                'evidence': f"Excess cover share: {len(excess)/len(latest_inventory):.1%}",
                'owner': 'Merchandising / planning',
            })

    store_perf = sales_f.groupby('store_name', as_index=False)[['net_revenue', 'gross_profit']].sum()
    if not store_perf.empty and not latest_inventory.empty:
        stockout_by_store = latest_inventory.groupby('store_name', as_index=False)['stockout_flag'].mean()
        store_perf = store_perf.merge(stockout_by_store, on='store_name', how='left')
        high_rev_cut = store_perf['net_revenue'].quantile(0.75)
        pressure = store_perf[(store_perf['net_revenue'] >= high_rev_cut) & (store_perf['stockout_flag'] >= store_perf['stockout_flag'].median())]
        if not pressure.empty:
            focus_stores = ', '.join(pressure.sort_values('net_revenue', ascending=False)['store_name'].head(3).tolist())
            recs.append({
                'priority': 3,
                'theme': 'Store operations',
                'recommendation': 'Prioritise in-stock execution at the highest-value branches before expanding assortment or promotions.',
                'why_it_matters': f"High-revenue stores are still carrying above-median stockout pressure, with the clearest focus on {focus_stores}.",
                'evidence': f"Pressure stores identified: {len(pressure)} | Current overall stockout rate: {summary['stockout_rate']:.1%}",
                'owner': 'Retail operations',
            })

    discount_mix = sales_f.copy()
    if not discount_mix.empty:
        no_disc = discount_mix[discount_mix['discount_pct'] == 0]
        disc = discount_mix[discount_mix['discount_pct'] > 0]
        no_disc_margin = float((no_disc['gross_profit'].sum() / no_disc['net_revenue'].sum())) if not no_disc.empty and no_disc['net_revenue'].sum() else 0
        disc_margin = float((disc['gross_profit'].sum() / disc['net_revenue'].sum())) if not disc.empty and disc['net_revenue'].sum() else 0
        if not disc.empty and disc_margin < no_disc_margin:
            recs.append({
                'priority': 4,
                'theme': 'Pricing and promotions',
                'recommendation': 'Tighten discount depth and reserve promotions for traffic-driving or strategic SKUs only.',
                'why_it_matters': f"Discounted mix is {summary['discounted_mix']:.1%} of transactions, but discounted margin trails full-price margin.",
                'evidence': f"Discounted margin: {disc_margin:.1%} | Full-price margin: {no_disc_margin:.1%}",
                'owner': 'Commercial / pricing',
            })

    sku = sales_f.groupby(['sku', 'product_name', 'category'], as_index=False)[['net_revenue', 'gross_profit']].sum()
    if not sku.empty:
        sku = sku.sort_values('net_revenue', ascending=False).reset_index(drop=True)
        sku['revenue_share'] = sku['net_revenue'] / sku['net_revenue'].sum()
        sku['cum_share'] = sku['revenue_share'].cumsum()
        hero = sku[sku['cum_share'] <= 0.8]
        if not hero.empty:
            recs.append({
                'priority': 5,
                'theme': 'Assortment strategy',
                'recommendation': 'Protect hero SKUs with tighter availability targets and simplify the long tail where demand is weak.',
                'why_it_matters': f"Only {len(hero):,} SKUs generate roughly 80% of revenue in this slice, indicating strong assortment concentration.",
                'evidence': f"Hero SKU share of assortment: {len(hero)/len(sku):.1%}",
                'owner': 'Merchandising',
            })

    recs_df = pd.DataFrame(recs).sort_values('priority') if recs else pd.DataFrame(columns=['priority','theme','recommendation','why_it_matters','evidence','owner'])

    if recs_df.empty:
        st.info('No recommendations were generated for the current filters.')
        return

    top1, top2 = st.columns(2)
    with top1:
        render_insight_card(
            'Top recommendation',
            f"<b>{recs_df.iloc[0]['recommendation']}</b><br><br>{recs_df.iloc[0]['why_it_matters']}",
            'Priority 1',
        )
    with top2:
        render_insight_card(
            'Management takeaway',
            'Use this page as the closing narrative in your portfolio demo: what happened, why it matters, and what the business should do next.',
            'Storytelling',
        )

    st.subheader('Prioritised recommendation queue')
    st.dataframe(recs_df, use_container_width=True, hide_index=True)
    st.download_button(
        'Download business recommendations as CSV',
        data=recs_df.to_csv(index=False).encode('utf-8'),
        file_name='mamboo_business_recommendations.csv',
        mime='text/csv',
    )


inject_css()
sales, inventory, stores = get_data()
min_date = sales['order_date'].dt.date.min()
max_date = sales['order_date'].dt.date.max()

st.markdown(
    """
    <div class='hero-card'>
        <div class='section-label'>Portfolio project</div>
        <div class='hero-title'>Mamboo Retail Intelligence Dashboard</div>
        <div class='hero-subtitle'>A polished Streamlit analytics app for a multi-branch South African home and storage retailer. It combines sales performance, assortment analysis, inventory health, and promotion effectiveness into one executive-facing dashboard.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header('Filters')
    start_date = st.date_input('Start date', value=min_date, min_value=min_date, max_value=max_date)
    end_date = st.date_input('End date', value=max_date, min_value=min_date, max_value=max_date)
    province_options = sorted(sales['province'].dropna().unique().tolist())
    category_options = sorted(sales['category'].dropna().unique().tolist())
    channel_options = sorted(sales['channel'].dropna().unique().tolist())
    segment_options = sorted(sales['customer_segment'].dropna().unique().tolist())
    provinces = st.multiselect('Province', province_options)
    categories = st.multiselect('Category', category_options)
    channels = st.multiselect('Channel', channel_options, default=channel_options)
    segments = st.multiselect('Customer segment', segment_options)
    st.caption('Tip: keep at least one channel selected to avoid an empty view.')

sales_f, inv_f = filter_data(sales, inventory, start_date, end_date, provinces, categories, channels, segments)
if sales_f.empty:
    st.warning('No data matches the current filters.')
    st.stop()

comparison = compute_comparison_window(sales, inventory, start_date, end_date, provinces, categories, channels, segments)
summary = compute_summary(sales_f, inv_f)
render_filter_summary(start_date, end_date, provinces, categories, channels, segments)

mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
with mc1:
    st.metric('Revenue', fmt_currency(summary['revenue']), fmt_delta(summary['revenue'], comparison['revenue']))
with mc2:
    st.metric('Gross Profit', fmt_currency(summary['profit']), fmt_delta(summary['profit'], comparison['profit']))
with mc3:
    st.metric('Orders', f"{summary['orders']:,}", fmt_delta(summary['orders'], comparison['orders']))
with mc4:
    st.metric('Units Sold', f"{summary['units']:,}", fmt_delta(summary['units'], comparison['units']))
with mc5:
    st.metric('Avg Basket', fmt_currency(summary['avg_basket']), fmt_delta(summary['avg_basket'], comparison['avg_basket']))
with mc6:
    st.metric('Gross Margin', fmt_pct(summary['margin']), fmt_delta(summary['margin'], comparison['margin']))

mc7, mc8, mc9, mc10 = st.columns(4)
with mc7:
    st.metric('Sell-through', fmt_pct(summary['sell_through']), fmt_delta(summary['sell_through'], comparison['sell_through']))
with mc8:
    st.metric('Stockout Rate', fmt_pct(summary['stockout_rate']), fmt_delta(summary['stockout_rate'], comparison['stockout_rate']))
with mc9:
    st.metric('Inventory Value', fmt_currency(summary['inventory_value']), fmt_delta(summary['inventory_value'], comparison['inventory_value']))
with mc10:
    st.metric('Low Cover Share', fmt_pct(summary['low_cover_share']), fmt_delta(summary['low_cover_share'], comparison['low_cover_share']))

pages = st.tabs([
    'Executive Overview',
    'Store Performance',
    'Category & SKU',
    'Inventory Health',
    'Promotions',
    'Opportunity Queue',
    'Business Recommendations',
])

with pages[0]:
    executive_page(sales_f, inv_f, summary)
with pages[1]:
    store_page(sales_f, inv_f)
with pages[2]:
    category_page(sales_f)
with pages[3]:
    inventory_page(inv_f)
with pages[4]:
    promo_page(sales_f)
with pages[5]:
    opportunity_page(sales_f, inv_f)
with pages[6]:
    business_recommendations_page(sales_f, inv_f, summary)

st.caption('Built with Streamlit, Python, Plotly, and SQLite using synthetic retail data for portfolio use.')
