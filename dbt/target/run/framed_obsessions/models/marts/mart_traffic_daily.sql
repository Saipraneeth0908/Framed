
  
    

  create  table "framedobsessions"."mart"."mart_traffic_daily__dbt_tmp"
  
  
    as
  
  (
    
select
    started_at::date            as day,
    utm_source,
    device,
    country,
    count(*)                    as sessions,
    count(distinct visitor_key) as visitors,
    round(avg(duration_seconds)) as avg_duration_seconds,
    count(*) filter (where event_count = 1) as bounces,
    round(100.0 * count(*) filter (where event_count = 1) / nullif(count(*), 0), 2) as bounce_pct
from "framedobsessions"."stg"."stg_sessions"
group by 1, 2, 3, 4
  );
  