-- Analysis views over the cleaned SPI tables. Rebuilt on every run.
-- Each block answers one of the project's three questions; the reasoning
-- behind each definition is in docs/methods.md.

------------------------------------------------------------------------------
-- Shared: fixed basket weights and one national price per item-week
------------------------------------------------------------------------------

-- PBS weights are fixed at the 2015-16 base, so the median over weeks is
-- simply the published weight (and robust to an occasional misparse).
CREATE OR REPLACE VIEW weights AS
SELECT item_no,
       median(weight_combined) AS w_combined,
       median(weight_q1)       AS w_q1
FROM summary_items
WHERE item_no IS NOT NULL
GROUP BY item_no;

-- National average price: PBS's own figure from the summary where we have
-- it, else the annex national average, else the mean of the 17 city averages.
CREATE OR REPLACE VIEW item_national AS
WITH city_mean AS (
    SELECT week_end, item_no, any_value(short_name) AS short_name,
           any_value("group") AS item_group, any_value(spec_version) AS spec_version,
           avg(price_avg) AS mean_city
    FROM prices GROUP BY ALL
), keys AS (
    SELECT week_end, item_no FROM city_mean
    UNION SELECT week_end, item_no FROM summary_items WHERE item_no IS NOT NULL
)
SELECT k.week_end, k.item_no,
       coalesce(c.short_name, i.short_name) AS short_name,
       coalesce(c.item_group, i."group")     AS item_group,
       c.spec_version,
       coalesce(s.price, n.nat_avg, c.mean_city) AS price,
       CASE WHEN s.price IS NOT NULL THEN 'summary'
            WHEN n.nat_avg IS NOT NULL THEN 'annex_national'
            ELSE 'city_mean' END AS price_source
FROM keys k
LEFT JOIN city_mean c USING (week_end, item_no)
LEFT JOIN (SELECT week_end, item_no, any_value(price) AS price FROM summary_items
           WHERE item_no IS NOT NULL GROUP BY ALL) s USING (week_end, item_no)
LEFT JOIN national n USING (week_end, item_no)
LEFT JOIN (SELECT item_no, any_value(short_name) AS short_name, any_value("group") AS "group"
           FROM items GROUP BY 1) i USING (item_no);

------------------------------------------------------------------------------
-- Q1. Which city pays the most for the same basket, and is that stable?
------------------------------------------------------------------------------
-- "Same basket" = the kitchen items (SPI items 1-29) that were priced in all
-- 17 cities that week. Each city's price is expressed relative to the
-- 17-city mean for that item, then averaged with the combined SPI weights.
-- 100 = national average; 105 = the basket costs 5% more than average.

CREATE OR REPLACE VIEW kitchen_complete AS
SELECT week_end, item_no
FROM prices
WHERE "group" = 'kitchen'
GROUP BY week_end, item_no
HAVING count(price_avg) = 17;

CREATE OR REPLACE VIEW city_index AS
WITH p AS (
    SELECT pr.week_end, pr.city, pr.city_code, pr.item_no, pr.price_avg,
           avg(pr.price_avg) OVER (PARTITION BY pr.week_end, pr.item_no) AS item_mean
    FROM prices pr
    JOIN kitchen_complete k USING (week_end, item_no)
)
SELECT week_end, city, city_code,
       100 * sum(coalesce(w.w_combined, 1) * price_avg / item_mean)
           / sum(coalesce(w.w_combined, 1))      AS idx_weighted,
       100 * exp(avg(ln(price_avg / item_mean))) AS idx_geometric,
       count(*)                                  AS n_items
FROM p
LEFT JOIN weights w USING (item_no)
GROUP BY week_end, city, city_code;

CREATE OR REPLACE VIEW city_rank AS
SELECT *,
       rank() OVER (PARTITION BY week_end ORDER BY idx_weighted DESC) AS rank_dear
FROM city_index;

CREATE OR REPLACE VIEW city_stability AS
SELECT city, city_code,
       count(*)                                        AS weeks,
       round(avg(idx_weighted), 2)                     AS mean_idx,
       round(stddev_samp(idx_weighted), 2)             AS sd_idx,
       round(min(idx_weighted), 2)                     AS min_idx,
       round(max(idx_weighted), 2)                     AS max_idx,
       median(rank_dear)                               AS median_rank,
       round(100 * avg((rank_dear = 1)::INT), 1)        AS pct_weeks_dearest,
       round(100 * avg((rank_dear <= 3)::INT), 1)       AS pct_weeks_top3,
       round(100 * avg((rank_dear >= 15)::INT), 1)      AS pct_weeks_bottom3
FROM city_rank
GROUP BY city, city_code
ORDER BY mean_idx DESC;

-- Which items make a city dear? Mean relative price per city x item.
CREATE OR REPLACE VIEW city_item_premium AS
WITH p AS (
    SELECT pr.week_end, pr.city, pr.item_no, pr.short_name, pr.price_avg,
           avg(pr.price_avg) OVER (PARTITION BY pr.week_end, pr.item_no) AS item_mean
    FROM prices pr JOIN kitchen_complete k USING (week_end, item_no)
)
SELECT city, item_no, any_value(short_name) AS short_name,
       round(100 * (avg(price_avg / item_mean) - 1), 1) AS premium_pct,
       count(*) AS weeks
FROM p GROUP BY city, item_no;

------------------------------------------------------------------------------
-- Q2. Do poorer households face different inflation?
------------------------------------------------------------------------------

CREATE OR REPLACE VIEW quintile_yoy AS
SELECT week_end,
       max(yoy_pct) FILTER (WHERE "group" = 'Q1')       AS q1,
       max(yoy_pct) FILTER (WHERE "group" = 'Q2')       AS q2,
       max(yoy_pct) FILTER (WHERE "group" = 'Q3')       AS q3,
       max(yoy_pct) FILTER (WHERE "group" = 'Q4')       AS q4,
       max(yoy_pct) FILTER (WHERE "group" = 'Q5')       AS q5,
       max(yoy_pct) FILTER (WHERE "group" = 'Combined') AS combined,
       max(spi)     FILTER (WHERE "group" = 'Q1')       AS spi_q1,
       max(spi)     FILTER (WHERE "group" = 'Q5')       AS spi_q5,
       max(spi)     FILTER (WHERE "group" = 'Combined') AS spi_combined
FROM quintiles
GROUP BY week_end
ORDER BY week_end;

-- Item contributions (pp) to YoY inflation for the lowest quintile vs the
-- combined index; the difference shows which items open the gap.
CREATE OR REPLACE VIEW gap_contrib AS
SELECT y.week_end, y.item_no,
       CASE y.item_no WHEN 0  THEN 'Missing weeks (unattributed)'
                      WHEN -1 THEN 'PBS revisions'
                      ELSE i.short_name END AS short_name,
       any_value(y.missing_weeks) AS missing_weeks,
       max(contrib_pp) FILTER (WHERE basket = 'q1')       AS q1_pp,
       max(contrib_pp) FILTER (WHERE basket = 'combined') AS combined_pp,
       max(weight)     FILTER (WHERE basket = 'q1')       AS w_q1,
       max(weight)     FILTER (WHERE basket = 'combined') AS w_combined,
       q1_pp - combined_pp                                AS gap_pp
FROM yoy_contrib y
LEFT JOIN (SELECT item_no, any_value(short_name) AS short_name FROM items GROUP BY 1) i USING (item_no)
GROUP BY y.week_end, y.item_no, i.short_name;

------------------------------------------------------------------------------
-- Q3. How large is the Ramadan effect by item, across years?
------------------------------------------------------------------------------
-- Ramadan as observed in Pakistan (first and last fast). Weekly data makes
-- +/-1 day irrelevant: SPI prices are collected once a week.
CREATE OR REPLACE TABLE ramadan AS
SELECT * FROM (VALUES
    (2023, DATE '2023-03-24', DATE '2023-04-21'),
    (2024, DATE '2024-03-12', DATE '2024-04-09'),
    (2025, DATE '2025-03-02', DATE '2025-03-30'),
    (2026, DATE '2026-02-19', DATE '2026-03-20')
) t(year, first_fast, last_fast);

-- Window geometry (same for Ramadan and for the counterfactual):
--   baseline: price dates 8-35 days before the anchor (4 weeks, skipping the
--             final week before it, when stocking-up already moves prices)
--   run-up:   the price date in the 7 days before the anchor
--   window:   price dates from the anchor to the last fast (Ramadan), or
--             anchor + 28 days (counterfactual)
--
-- Counterfactual: the same window shape anchored on every week that does
-- not touch Ramadan, per item. Its median is the item's "typical month"
-- change (trend + general inflation). The Ramadan effect is the Ramadan
-- change minus that typical change, in percentage points. We do NOT deflate
-- by the overall SPI: it contains the Ramadan items themselves, and it would
-- make every fixed-price item look like it fell.

CREATE OR REPLACE VIEW typical_window_change AS
WITH anchors AS (
    SELECT n.item_no, n.week_end AS anchor
    FROM item_national n
    WHERE NOT EXISTS (
        SELECT 1 FROM ramadan r
        WHERE n.week_end - 35 <= r.last_fast + 7 AND n.week_end + 28 >= r.first_fast - 35)
), w AS (
    SELECT a.item_no, a.anchor,
           avg(b.price) FILTER (WHERE b.week_end BETWEEN a.anchor - 35 AND a.anchor - 8) AS p_base,
           avg(b.price) FILTER (WHERE b.week_end BETWEEN a.anchor AND a.anchor + 28)    AS p_win,
           count(*) FILTER (WHERE b.week_end BETWEEN a.anchor - 35 AND a.anchor - 8)    AS n_base,
           count(*) FILTER (WHERE b.week_end BETWEEN a.anchor AND a.anchor + 28)        AS n_win,
           count(DISTINCT b.spec_version)                                               AS n_specs
    FROM anchors a
    JOIN item_national b ON b.item_no = a.item_no AND b.week_end BETWEEN a.anchor - 35 AND a.anchor + 28
    GROUP BY a.item_no, a.anchor
)
SELECT item_no,
       100 * median(p_win / p_base - 1)                                   AS typical_pct,
       100 * (quantile_cont(p_win / p_base - 1, 0.75)
              - quantile_cont(p_win / p_base - 1, 0.25))                  AS typical_iqr_pp,
       count(*)                                                           AS n_windows
FROM w
WHERE n_base >= 3 AND n_win >= 3 AND coalesce(n_specs, 1) <= 1
GROUP BY item_no;

CREATE OR REPLACE VIEW ramadan_effect AS
WITH w AS (
    SELECT r.year, n.item_no, n.short_name, n.item_group, n.spec_version, n.price,
           q.spi_combined,
           CASE WHEN n.week_end BETWEEN r.first_fast - 35 AND r.first_fast - 8 THEN 'baseline'
                WHEN n.week_end BETWEEN r.first_fast - 7  AND r.first_fast - 1 THEN 'runup'
                WHEN n.week_end BETWEEN r.first_fast      AND r.last_fast      THEN 'ramadan'
           END AS phase
    FROM item_national n
    JOIN ramadan r ON n.week_end BETWEEN r.first_fast - 35 AND r.last_fast
    LEFT JOIN quintile_yoy q USING (week_end)
), agg AS (
    SELECT year, item_no, any_value(short_name) AS short_name, any_value(item_group) AS item_group,
           avg(price) FILTER (WHERE phase = 'baseline') AS p_base,
           avg(price) FILTER (WHERE phase = 'runup')    AS p_runup,
           avg(price) FILTER (WHERE phase = 'ramadan')  AS p_ramadan,
           max(price) FILTER (WHERE phase = 'ramadan')  AS p_peak,
           avg(spi_combined) FILTER (WHERE phase = 'baseline') AS spi_base,
           avg(spi_combined) FILTER (WHERE phase = 'ramadan')  AS spi_ramadan,
           count(*) FILTER (WHERE phase = 'baseline') AS n_base,
           count(*) FILTER (WHERE phase = 'ramadan')  AS n_ramadan,
           count(DISTINCT spec_version)               AS n_specs
    FROM w GROUP BY year, item_no
)
SELECT a.*,
       round(100 * (p_ramadan / p_base - 1), 2)                AS chg_pct,
       round(100 * (p_runup / p_base - 1), 2)                  AS runup_pct,
       round(100 * (p_peak / p_base - 1), 2)                   AS peak_pct,
       round(100 * (spi_ramadan / spi_base - 1), 2)            AS spi_chg_pct,
       round(t.typical_pct, 2)                                 AS typical_pct,
       round(t.typical_iqr_pp, 2)                              AS typical_iqr_pp,
       round(100 * (p_ramadan / p_base - 1) - t.typical_pct, 2) AS net_effect_pct,
       -- "clear" = bigger than the item's normal 4-week swing (IQR). For
       -- strongly seasonal produce the counterfactual is weak (all three
       -- Ramadans so far fell in spring), and this keeps it honest.
       abs(100 * (p_ramadan / p_base - 1) - t.typical_pct) > t.typical_iqr_pp AS clear,
       (n_base >= 3 AND n_ramadan >= 3 AND coalesce(n_specs, 1) <= 1
        AND t.n_windows >= 20)                                 AS usable
FROM agg a
LEFT JOIN typical_window_change t USING (item_no);
