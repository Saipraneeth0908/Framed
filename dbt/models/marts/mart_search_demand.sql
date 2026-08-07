{{ config(materialized='table', tags=['hourly']) }}
select
    occurred_at::date          as day,
    lower(props ->> 'term')    as term,
    count(*)                   as searches,
    count(distinct session_id) as sessions,
    sum(case when event_name = 'search_zero_results' then 1 else 0 end) as zero_result_searches
from {{ ref('stg_events') }}
where event_name in ('search', 'search_zero_results')
  and nullif(props ->> 'term', '') is not null
group by 1, 2
