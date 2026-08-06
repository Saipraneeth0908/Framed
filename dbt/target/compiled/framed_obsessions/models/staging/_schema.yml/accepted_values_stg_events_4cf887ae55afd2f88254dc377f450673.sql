
    
    

with all_values as (

    select
        event_name as value_field,
        count(*) as n_records

    from "framedobsessions"."stg"."stg_events"
    group by event_name

)

select *
from all_values
where value_field not in (
    'page_view','product_view','search','search_zero_results','filter_apply','config_change','add_to_cart','remove_from_cart','cart_view','checkout_start','checkout_step','checkout_error','purchase','wishlist_add','wall_preview_open','newsletter_submit','outbound_click'
)


