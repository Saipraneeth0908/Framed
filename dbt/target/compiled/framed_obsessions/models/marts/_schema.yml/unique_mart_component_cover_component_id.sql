
    
    

select
    component_id as unique_field,
    count(*) as n_records

from "framedobsessions"."mart"."mart_component_cover"
where component_id is not null
group by component_id
having count(*) > 1


