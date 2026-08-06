
    
    

select
    cohort_month as unique_field,
    count(*) as n_records

from "framedobsessions"."mart"."mart_customer_cohorts"
where cohort_month is not null
group by cohort_month
having count(*) > 1


