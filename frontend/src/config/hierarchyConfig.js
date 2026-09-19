// DISCOM 9-Tier Utility Hierarchy Configuration Schema
export const DISCOM_HIERARCHY_CONFIG = {
  Circle: {
    tier_level: 1,
    label: "Electrical Circle",
    category: "administrative",
    geom_type: "MULTIPOLYGON",
    source_layer: "circle",
    minZoom: 4,
    maxZoom: 10,
    paint: {
      fill: {
        'fill-color': ['coalesce', ['get', 'fill_hex'], '#6366f1'],
        'fill-opacity': 0.25
      },
      line: {
        'line-color': ['coalesce', ['get', 'fill_hex'], '#4338ca'],
        'line-width': 2.5,
        'line-opacity': 0.85
      }
    }
  },
  Division: {
    tier_level: 2,
    label: "Operational Division",
    category: "administrative",
    geom_type: "MULTIPOLYGON",
    source_layer: "division",
    minZoom: 7,
    maxZoom: 12,
    paint: {
      fill: {
        'fill-color': '#0ea5e9',
        'fill-opacity': 0.15
      },
      line: {
        'line-color': '#0284c7',
        'line-width': 2.0,
        'line-dasharray': [2, 1]
      }
    }
  },
  Subdivision: {
    tier_level: 3,
    label: "Subdivision (Block/Tehsil)",
    category: "administrative",
    geom_type: "MULTIPOLYGON",
    source_layer: "subdivision",
    minZoom: 9,
    maxZoom: 14,
    paint: {
      fill: {
        'fill-color': '#10b981',
        'fill-opacity': 0.1
      },
      line: {
        'line-color': '#059669',
        'line-width': 1.2
      }
    }
  },
  Section: {
    tier_level: 4,
    label: "Utility Section",
    category: "administrative",
    geom_type: "MULTIPOLYGON",
    source_layer: "section",
    minZoom: 10,
    maxZoom: 15,
    paint: {
      fill: {
        'fill-color': '#f59e0b',
        'fill-opacity': 0.08
      },
      line: {
        'line-color': '#d97706',
        'line-width': 1.0,
        'line-dasharray': [1, 1]
      }
    }
  },
  GSS: {
    tier_level: 5,
    label: "Grid Substation (>=132kV)",
    category: "electrical_node",
    geom_type: "POINT",
    source_layer: "gss",
    minZoom: 8,
    maxZoom: 22,
    paint: {
      circle: {
        'circle-radius': 8,
        'circle-color': '#dc2626',
        'circle-stroke-width': 2.5,
        'circle-stroke-color': '#ffffff'
      }
    }
  },
  PSS: {
    tier_level: 6,
    label: "Primary Substation (33/11kV)",
    category: "electrical_node",
    geom_type: "POINT",
    source_layer: "pss",
    minZoom: 9,
    maxZoom: 22,
    paint: {
      circle: {
        'circle-radius': 6.5,
        'circle-color': '#ea580c',
        'circle-stroke-width': 2.0,
        'circle-stroke-color': '#ffffff'
      }
    }
  },
  DSS: {
    tier_level: 7,
    label: "Distribution Substation (11/0.415kV)",
    category: "electrical_node",
    geom_type: "POINT",
    source_layer: "dss",
    minZoom: 11,
    maxZoom: 22,
    paint: {
      circle: {
        'circle-radius': 4.5,
        'circle-color': '#8b5cf6',
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#ffffff'
      }
    }
  },
  Feeders: {
    tier_level: 8,
    label: "11kV / 33kV Feeder Lines",
    category: "electrical_line",
    geom_type: "MULTILINESTRING",
    source_layer: "feeders",
    minZoom: 10,
    maxZoom: 22,
    paint: {
      line: {
        'line-color': '#eab308',
        'line-width': 2.2,
        'line-opacity': 0.9
      }
    }
  },
  Consumers: {
    tier_level: 9,
    label: "Consumer Settlement Nodes",
    category: "consumer_cluster",
    geom_type: "POINT",
    source_layer: "consumers",
    minZoom: 12,
    maxZoom: 22,
    paint: {
      circle: {
        'circle-radius': 3.5,
        'circle-color': '#06b6d4',
        'circle-stroke-width': 1.0,
        'circle-stroke-color': '#ffffff',
        'circle-opacity': 0.8
      }
    }
  }
};
