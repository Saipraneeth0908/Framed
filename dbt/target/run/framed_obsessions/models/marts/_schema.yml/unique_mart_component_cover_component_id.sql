
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    component_id as unique_field,
    count(*) as n_records

from "framedobsessions"."mart"."mart_component_cover"
where component_id is not null
group by component_id
having count(*) > 1



  
  
      
    ) dbt_internal_test