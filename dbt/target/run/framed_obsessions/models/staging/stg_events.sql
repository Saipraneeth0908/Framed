
      
        delete from "framedobsessions"."stg"."stg_events" as DBT_INTERNAL_DEST
        where (event_id, occurred_at) in (
            select distinct event_id, occurred_at
            from "stg_events__dbt_tmp222825676706" as DBT_INTERNAL_SOURCE
        );

    

    insert into "framedobsessions"."stg"."stg_events" ("event_id", "occurred_at", "received_at", "session_id", "visitor_key", "event_name", "path", "product_id", "variant_id", "cart_id", "device", "browser", "os", "country", "referrer_host", "utm_source", "utm_medium", "utm_campaign", "props", "event_version")
    (
        select "event_id", "occurred_at", "received_at", "session_id", "visitor_key", "event_name", "path", "product_id", "variant_id", "cart_id", "device", "browser", "os", "country", "referrer_host", "utm_source", "utm_medium", "utm_campaign", "props", "event_version"
        from "stg_events__dbt_tmp222825676706"
    )
  