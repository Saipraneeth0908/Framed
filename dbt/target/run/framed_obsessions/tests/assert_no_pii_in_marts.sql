
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  -- Metabase reads the mart schema as bi_reader. Nothing in there may be a
-- customer identifier: this test fails the build if a future model quietly
-- selects an email or a name into a mart.
select table_name, column_name
from information_schema.columns
where table_schema = 'mart'
  and (
      column_name ilike '%email%'
   or column_name ilike '%phone%'
   or column_name in ('name', 'customer_name', 'ship_name', 'street', 'address')
  )
  
  
      
    ) dbt_internal_test