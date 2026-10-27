
PRESETS = {
    "FINE": {
        "touch_diameter": 0.28,
        "touch_depth": 0.15,
        "neck_diameter": 0.50,
        "neck_length": 2.20,
        "pillar_diameter": 1.20,
        "base_diameter": 4.20,
        "base_height": 1.60,
        "spacing": 1.50,
        "safe_distance": 0.55,
        "overhang_angle": 45.0,
        "tree_merge_distance": 4.00,
        "branch_descent": 4.00,
        "truss_diameter": 0.90,
        "truss_minimum_height": 3.00,
        "truss_spacing": 3.00,
        "truss_top_spacing": 0.00,
        "truss_distance_limit": 6.00,
        "tree_branch_diameter": 0.90,
        "tree_trunk_diameter": 1.60,
        "tree_model_clearance": 0.35,
        "tree_tip_cone_length": 0.30,
        "tree_tip_neck_length": 0.30,
    },
    "BALANCED": {
        "touch_diameter": 0.30,
        "touch_depth": 0.18,
        "neck_diameter": 0.50,
        "neck_length": 2.10,
        "pillar_diameter": 1.35,
        "base_diameter": 4.60,
        "base_height": 1.80,
        "spacing": 1.45,
        "safe_distance": 0.55,
        "overhang_angle": 45.0,
        "tree_merge_distance": 4.00,
        "branch_descent": 4.50,
        "truss_diameter": 1.10,
        "truss_minimum_height": 2.75,
        "truss_spacing": 2.75,
        "truss_top_spacing": 0.00,
        "truss_distance_limit": 6.50,
        "tree_branch_diameter": 1.00,
        "tree_trunk_diameter": 1.80,
        "tree_model_clearance": 0.45,
        "tree_tip_cone_length": 0.32,
        "tree_tip_neck_length": 0.35,
    },
    "ROBUST": {
        "touch_diameter": 0.35,
        "touch_depth": 0.20,
        "neck_diameter": 0.55,
        "neck_length": 2.00,
        "pillar_diameter": 1.50,
        "base_diameter": 5.00,
        "base_height": 2.00,
        "spacing": 1.35,
        "safe_distance": 0.50,
        "overhang_angle": 45.0,
        "tree_merge_distance": 4.00,
        "branch_descent": 5.00,
        "truss_diameter": 1.30,
        "truss_minimum_height": 2.50,
        "truss_spacing": 2.50,
        "truss_top_spacing": 0.00,
        "truss_distance_limit": 6.50,
        "tree_branch_diameter": 1.15,
        "tree_trunk_diameter": 2.10,
        "tree_model_clearance": 0.55,
        "tree_tip_cone_length": 0.36,
        "tree_tip_neck_length": 0.40,
    },
}

def apply_preset(props, preset_name):
    data = PRESETS.get(preset_name)
    if not data:
        return
    for key, value in data.items():
        if hasattr(props, key):
            setattr(props, key, value)


def as_dict(preset_name):
    return dict(PRESETS[preset_name])
