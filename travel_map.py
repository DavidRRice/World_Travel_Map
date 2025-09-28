# -*- coding: utf-8 -*-
"""
Created on Sun Aug 24 15:37:00 2025

@author: drice

Travel Map CLI (with overlap hatching)
--------------------------------------
- Assumes a "NaturalEarth" folder next to this script with:
    ne_10m_admin_0_countries.shp (+ .shx/.dbf/.prj/etc.)
    ne_10m_admin_1_states_provinces.shp (+ companions)
- Reads one or more text files of ISO3 codes (one per line).
- Each list gets a base color; if a country appears in multiple lists,
  we overlay hatches using the *other* list colors:
    2nd membership: '//' hatch with 2nd list's color
    3rd membership: '\\\\' (denser) hatch with 3rd list's color
    4th+: optional '..' dot hatch in neutral gray
"""

import os
import sys
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import matplotlib as mpl

# ----------------------------- helpers ---------------------------------

def _union(gs):
    return gs.union_all() if hasattr(gs, "union_all") else gs.unary_union

def mainland_cluster(geom, max_km=700):
    if geom is None:
        return None
    parts = list(geom.geoms) if getattr(geom, "geom_type", "") == "MultiPolygon" else [geom]
    if len(parts) <= 1:
        return geom
    cents = [p.centroid for p in parts]
    link  = max_km * 1000.0
    n = len(parts)
    adj = [[] for _ in range(n)]
    for i in range(n):
        ci = cents[i]
        for j in range(i+1, n):
            if ci.distance(cents[j]) <= link:
                adj[i].append(j); adj[j].append(i)
    comps, seen = [], set()
    for i in range(n):
        if i in seen: continue
        stack = [i]; seen.add(i); comp = []
        while stack:
            u = stack.pop(); comp.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v); stack.append(v)
        comps.append(comp)
    best = max(comps, key=lambda comp: sum(parts[k].area for k in comp))
    kept = [parts[k] for k in best] or [max(parts, key=lambda g: g.area)]
    merged = _union(gpd.GeoSeries(kept))
    if getattr(merged, "geom_type", "") == "GeometryCollection":
        polys = [g for g in merged.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        merged = _union(gpd.GeoSeries(polys)) if polys else max(parts, key=lambda g: g.area)
    return merged

def layer_from_iso3(cproj, iso3_list, max_km=700):
    if not iso3_list:
        return gpd.GeoDataFrame(columns=cproj.columns, geometry=[], crs=cproj.crs)
    if "ISO_A3_EH" in cproj.columns:
        iso_col = "ISO_A3_EH"
    elif "ISO_A3" in cproj.columns:
        iso_col = "ISO_A3"
    else:
        iso_col = "ADM0_A3"
    sel = cproj[cproj[iso_col].isin(iso3_list)].copy()
    if sel.empty:
        return sel
    sel["geometry"] = sel.geometry.apply(lambda g: mainland_cluster(g, max_km))
    return sel

def set_bounds_to_layers(ax, layers, pad=0.02):
    first = True
    for L in layers:
        if L is None or getattr(L, "empty", True):
            continue
        minx, miny, maxx, maxy = L.total_bounds
        if first:
            X1, Y1, X2, Y2 = minx, miny, maxx, maxy
            first = False
        else:
            X1, Y1 = min(X1, minx), min(Y1, miny)
            X2, Y2 = max(X2, maxx), max(Y2, maxy)
    if not first:
        dx, dy = X2 - X1, Y2 - Y1
        ax.set_xlim(X1 - pad*dx, X2 + pad*dx)
        ax.set_ylim(Y1 - pad*dy, Y2 + pad*dy)

def read_list_file(path, normalize=None):
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.strip() for ln in f.readlines()]
    items = [ln for ln in lines if ln and not ln.startswith("#")]
    if normalize:
        items = [normalize(x) for x in items]
    return items

def select_us_states(states_gdf, state_names):
    """
    Robustly select US states from Natural Earth admin-1 and return a GeoDataFrame.
    Accepts case-insensitive names; filters features to the United States.
    """
    if states_gdf is None or len(states_gdf) == 0:
        return states_gdf.iloc[0:0]

    cols = {c.lower(): c for c in states_gdf.columns}
    def col(name): return cols.get(name.lower())

    # Filter to US
    mask_us = None
    if col("admin") in states_gdf.columns:
        mask_us = (states_gdf[col("admin")] == "United States of America")
    if (mask_us is None or not mask_us.any()) and col("adm0_a3") in states_gdf.columns:
        mask_us = (states_gdf[col("adm0_a3")] == "USA")
    if (mask_us is None or not mask_us.any()) and col("iso_3166_2") in states_gdf.columns:
        mask_us = states_gdf[col("iso_3166_2")].fillna("").str.startswith("US-")

    us = states_gdf[mask_us] if mask_us is not None else states_gdf.iloc[0:0]
    if us.empty:
        return us

    # Build case-insensitive name index from likely name columns
    name_cols = [c for c in [col("name"), col("name_en"), col("name_local"), col("gn_name")] if c in us.columns]
    if not name_cols:
        name_cols = [next((c for c in us.columns if c.lower().startswith("name")), None)]
        name_cols = [c for c in name_cols if c]

    def norm(s): return str(s).strip().casefold()

    name_index = {}
    for idx, row in us.iterrows():
        for nc in name_cols:
            nm = row.get(nc)
            if nm is None:
                continue
            key = norm(nm)
            name_index.setdefault(key, set()).add(idx)

    abbr = {
        "al":"alabama","ak":"alaska","az":"arizona","ar":"arkansas","ca":"california","co":"colorado",
        "ct":"connecticut","de":"delaware","fl":"florida","ga":"georgia","hi":"hawaii","id":"idaho",
        "il":"illinois","in":"indiana","ia":"iowa","ks":"kansas","ky":"kentucky","la":"louisiana",
        "me":"maine","md":"maryland","ma":"massachusetts","mi":"michigan","mn":"minnesota","ms":"mississippi",
        "mo":"missouri","mt":"montana","ne":"nebraska","nv":"nevada","nh":"new hampshire","nj":"new jersey",
        "nm":"new mexico","ny":"new york","nc":"north carolina","nd":"north dakota","oh":"ohio","ok":"oklahoma",
        "or":"oregon","pa":"pennsylvania","ri":"rhode island","sc":"south carolina","sd":"south dakota",
        "tn":"tennessee","tx":"texas","ut":"utah","vt":"vermont","va":"virginia","wa":"washington",
        "wv":"west virginia","wi":"wisconsin","wy":"wyoming","dc":"district of columbia"
    }
    for k, v in abbr.items():
        nk = norm(k); nv = norm(v)
        if nk not in name_index and nv in name_index:
            name_index[nk] = name_index[nv]

    wanted = set()
    for nm in state_names:
        inds = name_index.get(norm(nm))
        if inds:
            wanted.update(inds)

    return us.loc[sorted(wanted)]

# ----------------------------- main ---------------------------------

def main():
    print("=== Travel Map Generator (overlap hatching) ===")

    # Shapefile paths fixed to NaturalEarth folder
    here = os.path.dirname(os.path.abspath(__file__))
    ne_folder = os.path.join(here, "NaturalEarth")
    shp_countries = os.path.join(ne_folder, "ne_10m_admin_0_countries.shp")
    shp_states    = os.path.join(ne_folder, "ne_10m_admin_1_states_provinces.shp")

    if not os.path.exists(shp_countries):
        print(f"ERROR: countries shapefile not found: {shp_countries}")
        sys.exit(1)
    if not os.path.exists(shp_states):
        print(f"WARNING: states shapefile not found: {shp_states} (states skipped)")
        shp_states = None

    # Projection choice: 1 = Mercator, 2 = Robinson
    proj_choice = input("Projection? Enter 1 for Web Mercator, 2 for Robinson [1]: ").strip() or "1"
    if proj_choice == "1":
        CRS_WORLD = 3857
    else:
        CRS_WORLD = "+proj=robin +lon_0=0 +datum=WGS84 +units=m +no_defs"
        
    # Ask about including outlying territories
    inc_outlying = input("Exclude outlying territories? (y/N): ").strip().lower()
    if inc_outlying.startswith("y"):
        max_km = 700   # cluster islands within 700 km
    else:
        max_km = 1e9   # effectively unlimited → mainlands only

    # Zoom option
    do_zoom = input("Zoom to selected countries? [y/N]: ").strip().lower() in ("y", "yes")

    # Output format
    ext_choice = input("Output format (svg/png/pdf/jpg) [png]: ").strip().lower() or "png"
    if ext_choice not in ("svg", "png", "pdf", "jpg", "jpeg"):
        print("Invalid choice, defaulting to png.")
        ext_choice = "png"

    # Color palette choice
    print("Choose color palette: 1, 2, or 3 [1]: ")
    pal_choice = input().strip() or "1"
    try:
        pal_choice = int(pal_choice)
    except:
        pal_choice = 1

    palettes = {
        1: ["#e6b800",  "#4daf4a", "#a52a2a", "#9467bd", "#1f77b4", "#8c564b"],
        2: ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948"],
        3: ["#2b83ba", "#abdda4", "#fdae61", "#d7191c", "#7570b3", "#66c2a5"],
        }
    palette = palettes.get(pal_choice, palettes[1])

    # Figure options
    figsize_w, figsize_h, dpi_out = 12, 7, 600

    # Load shapefiles
    countries = gpd.read_file(shp_countries)
    if "ADMIN" in countries.columns:
        countries = countries[countries["ADMIN"] != "Antarctica"].copy()
    countries_p = countries.to_crs(CRS_WORLD)

    states = None
    if shp_states:
        try:
            states = gpd.read_file(shp_states)
        except Exception as e:
            print(f"WARNING: could not read states shapefile: {e}")
            states = None

    # Read multiple country lists
    groups = []  # list of tuples: (label, iso3_list, color)
    idx = 1
    print("\nNow add one or more country lists (ISO3 codes).")
    while True:
        path = input(f"List {idx} - path to ISO3 text file (or press Enter to finish): ").strip()
        if not path:
            break
        if not os.path.exists(path):
            print("  File not found, please try again.")
            continue
        label = input(f"  Label for this list: ").strip() or f"List {idx}"
        iso3s = read_list_file(path, normalize=lambda s: s.strip().upper())
        iso3s = [c for c in iso3s if len(c) == 3]
        if not iso3s:
            print("  (No valid ISO3 codes found.)")
            continue
        color = palette[(idx-1) % len(palette)]
        groups.append((label, iso3s, color))
        idx += 1

    # Build membership map (iso -> [list indices in the order they were provided])
    membership = {}
    for list_idx, (_, iso3s, _) in enumerate(groups):
        for iso in iso3s:
            membership.setdefault(iso, []).append(list_idx)

    # Optional U.S. states list
    states_file = input("\nOptional: path to U.S. states list [skip]: ").strip()
    sel_states = []
    if states_file:
        if not os.path.exists(states_file):
            print("  States file not found; skipping.")
        else:
            sel_states = read_list_file(states_file)

    # Output filename
    out_name = input(f"\nOutput filename (without extension) [travel_map]: ").strip() or "travel_map"
    out_file = f"{out_name}.{ext_choice}"

    # ---------------- drawing ----------------
    fig, ax = plt.subplots(figsize=(figsize_w, figsize_h), facecolor="white")
    countries_p.boundary.plot(ax=ax, linewidth=0.4, color="0.5")

    # Base owner: first list wins for base color
    base_owner = {iso: members[0] for iso, members in membership.items()}
    # Plot base fills in batches by owner index
    for owner_idx in range(len(groups)):
        owner_iso = [iso for iso, o in base_owner.items() if o == owner_idx]
        if not owner_iso:
            continue
        layer = layer_from_iso3(countries_p, owner_iso, max_km=max_km)
        if layer is None or layer.empty:
            continue
        layer.plot(ax=ax, color=groups[owner_idx][2], edgecolor="0.2", linewidth=0.6, zorder=2)

    # Overlaid hatches for overlaps
    mpl.rcParams['hatch.linewidth'] = 1.5  # visible but not too heavy
    for iso, members in membership.items():
        if len(members) <= 1:
            continue
        geom_gdf = layer_from_iso3(countries_p, [iso], max_km=max_km)
        if geom_gdf is None or geom_gdf.empty:
            continue

        # Second membership hatch // with the 2nd list's color
        if len(members) >= 2:
            j = members[1]
            geom_gdf.plot(
                ax=ax,
                facecolor=(1, 1, 1, 0),     # transparent (works better than 'none')
                edgecolor=groups[j][2],     # hatch color comes from edgecolor
                hatch='////',               # a bit denser than '//' so it's obvious
                linewidth=0.1,              # must be > 0 on some backends
                zorder=5)
            
        # Third membership hatch: backslashes in 3rd list's color
        if len(members) >= 3:
            j = members[2]
            geom_gdf.plot(
                ax=ax,
                facecolor=(1, 1, 1, 0),
                edgecolor=groups[j][2],
                hatch='\\\\\\\\',           # escaped backslashes for Python string
                linewidth=0.1,
                zorder=6)

        # Fourth+ membership: subtle dotted hatch
        if len(members) >= 4:
            geom_gdf.plot(
                ax=ax,
                facecolor=(1, 1, 1, 0),
                edgecolor="0.4",
                hatch='..',
                linewidth=0.1,
                zorder=7
                )

    # Overlay selected U.S. states, if provided
    if states is not None and sel_states:
        us = states[states.get("admin", "") == "United States of America"]
        if not us.empty:
            us_sel = us[us.get("name", "").isin(sel_states)].to_crs(countries_p.crs)
            if not us_sel.empty:
                us_sel.plot(ax=ax, color="#3366cc", edgecolor="white", linewidth=0.4, zorder=8)

    
    # --- Overlay selected U.S. states, if provided ---
    us_sel = None
    if states is not None and sel_states:
        try:
            us_sel = select_us_states(states, sel_states)
            if us_sel is not None and not us_sel.empty:
                us_sel = us_sel.to_crs(countries_p.crs)
                us_sel.plot(ax=ax, color="#3366cc", edgecolor="none", alpha=1.0, zorder=9)
                us_sel.boundary.plot(ax=ax, color="black", linewidth=1.2, zorder=10)
                us_sel.boundary.plot(ax=ax, color="white", linewidth=0.6, zorder=11)
        except Exception as e:
            print(f"WARNING: states overlay failed: {e}")

    # Count matched states (for legend)
    states_count = 0
    try:
        if us_sel is not None and not us_sel.empty:
            states_count = len(us_sel)
    except NameError:
        pass

    group_counts = []
    for (lbl, codes, _c) in groups:
        gdf = layer_from_iso3(countries_p, codes, max_km=max_km)
        matched = 0 if gdf is None else len(gdf)
        group_counts.append(matched)

    # Legend (lists + optional states)
    handles = []

    # existing list labels with counts you computed above as `group_counts`
    if groups:
        for (lbl, _codes, c), matched in zip(groups, group_counts):
            handles.append(Patch(facecolor=c, edgecolor="0.2", label=f"{lbl} [{matched}]"))

    # add U.S. states entry if any matched
    if states_count > 0:
        handles.append(Patch(facecolor="#3366cc", edgecolor="white",
                         label=f"U.S. states [{states_count}]"))

    if handles:
        ax.legend(
            handles=handles, loc="lower center", frameon=True, framealpha=0.5,
            handlelength=0.9, handleheight=0.8, handletextpad=0.6,
            labelspacing=0.25, borderpad=0.3, fontsize=16
            )

    # Optional zoom to selected countries
    if membership and any(membership.values()) and (do_zoom):
        selected_iso = list(membership.keys())
        bounds_layer = layer_from_iso3(countries_p, selected_iso, max_km=max_km)
        if bounds_layer is not None and not bounds_layer.empty:
            set_bounds_to_layers(ax, [bounds_layer], pad=0.02)

    ax.set_axis_off()
    plt.tight_layout()
    plt.savefig(out_file, bbox_inches="tight", dpi=dpi_out)
    print(f"\nSaved map to: {out_file}")
    plt.show()

if __name__ == "__main__":
    main()
