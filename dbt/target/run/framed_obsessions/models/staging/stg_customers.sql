
  create view "framedobsessions"."stg"."stg_customers__dbt_tmp"
    
    
  as (
    select
    c.id            as customer_id,
    c.public_id,
    c.created_at,
    date_trunc('month', c.created_at)::date as cohort_month,
    c.marketing_opt_in
    -- Deliberately no email or name: the marts feed a BI tool, and PII that
    -- never enters the warehouse cannot leak out of a dashboard.
from "framedobsessions"."store"."customers" c
where c.archived_at is null
  );