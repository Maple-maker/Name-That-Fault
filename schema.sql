-- TM Parts Finder — Database Schema
-- Run this in Supabase SQL Editor

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- TABLES
-- ============================================================

CREATE TABLE equipment (
    id          text PRIMARY KEY,
    name        text NOT NULL,
    nomenclature text,
    image_url   text,
    tm_number   text NOT NULL,
    created_at  timestamptz DEFAULT now()
);

CREATE TABLE pmcs_items (
    id               uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    equipment_id     text NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
    item_number      text NOT NULL,
    inspection_interval text,
    item_to_inspect  text NOT NULL,
    technical_status text,
    nsn              text,
    tm_ref           text,
    search_vector    tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(item_number, '') || ' ' ||
                               coalesce(item_to_inspect, '') || ' ' ||
                               coalesce(technical_status, '') || ' ' ||
                               coalesce(nsn, '') || ' ' ||
                               coalesce(inspection_interval, ''))
    ) STORED,
    created_at       timestamptz DEFAULT now()
);

CREATE TABLE parts (
    id            uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    equipment_id  text NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
    nsn           text NOT NULL,
    part_number   text,
    nomenclature  text NOT NULL,
    source_tm     text,
    page_ref      text,
    created_at    timestamptz DEFAULT now()
);

-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX idx_pmcs_search ON pmcs_items USING GIN(search_vector);
CREATE INDEX idx_pmcs_inspect_trgm ON pmcs_items USING GIN(item_to_inspect gin_trgm_ops);
CREATE INDEX idx_pmcs_nsn_trgm ON pmcs_items USING GIN(nsn gin_trgm_ops);
CREATE INDEX idx_parts_nomenclature_trgm ON parts USING GIN(nomenclature gin_trgm_ops);
CREATE INDEX idx_parts_nsn_trgm ON parts USING GIN(nsn gin_trgm_ops);
CREATE INDEX idx_pmcs_equipment ON pmcs_items(equipment_id);
CREATE INDEX idx_parts_equipment ON parts(equipment_id);

-- ============================================================
-- SEARCH FUNCTION
-- ============================================================

CREATE OR REPLACE FUNCTION search_equipment(
    equip_id text,
    query text
)
RETURNS TABLE(
    source          text,
    id              uuid,
    item_number     text,
    inspection_interval text,
    item_to_inspect text,
    technical_status text,
    nsn             text,
    part_number     text,
    nomenclature    text,
    tm_ref          text,
    source_tm       text,
    page_ref        text,
    rank            real
) LANGUAGE plpgsql STABLE AS $$
BEGIN
    RETURN QUERY

    SELECT
        'pmcs'::text,
        pi.id,
        pi.item_number,
        pi.inspection_interval,
        pi.item_to_inspect,
        pi.technical_status,
        pi.nsn,
        NULL::text,
        NULL::text,
        pi.tm_ref,
        NULL::text,
        NULL::text,
        ts_rank(pi.search_vector, websearch_to_tsquery('english', query)) AS rank
    FROM pmcs_items pi
    WHERE pi.equipment_id = equip_id
      AND pi.search_vector @@ websearch_to_tsquery('english', query)

    UNION ALL

    SELECT
        'pmcs'::text,
        pi.id,
        pi.item_number,
        pi.inspection_interval,
        pi.item_to_inspect,
        pi.technical_status,
        pi.nsn,
        NULL::text,
        NULL::text,
        pi.tm_ref,
        NULL::text,
        NULL::text,
        GREATEST(
            similarity(pi.item_to_inspect, query),
            similarity(coalesce(pi.technical_status, ''), query),
            similarity(coalesce(pi.nsn, ''), query)
        ) AS rank
    FROM pmcs_items pi
    WHERE pi.equipment_id = equip_id
      AND (
          similarity(pi.item_to_inspect, query) > 0.15
          OR similarity(coalesce(pi.technical_status, ''), query) > 0.15
          OR similarity(coalesce(pi.nsn, ''), query) > 0.15
      )

    UNION ALL

    SELECT
        'parts'::text,
        p.id,
        NULL::text,
        NULL::text,
        NULL::text,
        NULL::text,
        p.nsn,
        p.part_number,
        p.nomenclature,
        NULL::text,
        p.source_tm,
        p.page_ref,
        ts_rank(
            to_tsvector('english', coalesce(p.nomenclature, '') || ' ' ||
                                    coalesce(p.nsn, '') || ' ' ||
                                    coalesce(p.part_number, '')),
            websearch_to_tsquery('english', query)
        ) AS rank
    FROM parts p
    WHERE p.equipment_id = equip_id
      AND to_tsvector('english', coalesce(p.nomenclature, '') || ' ' ||
                                   coalesce(p.nsn, '') || ' ' ||
                                   coalesce(p.part_number, ''))
          @@ websearch_to_tsquery('english', query)

    UNION ALL

    SELECT
        'parts'::text,
        p.id,
        NULL::text,
        NULL::text,
        NULL::text,
        NULL::text,
        p.nsn,
        p.part_number,
        p.nomenclature,
        NULL::text,
        p.source_tm,
        p.page_ref,
        GREATEST(
            similarity(p.nomenclature, query),
            similarity(coalesce(p.nsn, ''), query),
            similarity(coalesce(p.part_number, ''), query)
        ) AS rank
    FROM parts p
    WHERE p.equipment_id = equip_id
      AND (
          similarity(p.nomenclature, query) > 0.15
          OR similarity(coalesce(p.nsn, ''), query) > 0.15
          OR similarity(coalesce(p.part_number, ''), query) > 0.15
      )

    ORDER BY rank DESC
    LIMIT 25;
END;
$$;
