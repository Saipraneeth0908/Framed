{#
  dbt's default prefixes the target schema onto the configured one, giving
  stg_mart and stg_stg. The grants in migration 001 name `mart` and `stg`
  exactly, and bi_reader is scoped to `mart` -- so the schema names have to be
  literal, not derived.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
