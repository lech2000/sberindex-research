#!/usr/bin/env python3
"""Build decorative regional contours from the licensed OSM 2021 export."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import geopandas as gpd

SOURCE_URL='https://gist.githubusercontent.com/heaviss/7432d4fcb5e920324551cab143ec986a/raw/d247d8911f2f9b4d7f3f2bbd71b583e432f5959a/OSM_russian_boundaries.geojson'
SOURCE_SHA='20fdbdc7234a0670dba73fc40f87ae703b84e05ee09d53f16c0d909bc81cd33e'

def build(source, output):
    if hashlib.sha256(source.read_bytes()).hexdigest()!=SOURCE_SHA:
        raise ValueError('Unexpected geography source; review a new vintage before using it')
    repo=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('map_builder',repo/'landing-common/build_map.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    raw=json.loads(source.read_text())
    features=[f for f in raw['features'] if str(f['properties'].get('admin_level'))=='4']
    layer=gpd.GeoDataFrame.from_features(features,crs='EPSG:4326').to_crs(builder.MAP_CRS)
    layer.geometry=layer.geometry.simplify(12000,preserve_topology=True)
    bounds=tuple(float(x) for x in layer.total_bounds)
    scale=min(1536/(bounds[2]-bounds[0]),786/(bounds[3]-bounds[1]))
    offset=(32+(1536-(bounds[2]-bounds[0])*scale)/2,32+(786-(bounds[3]-bounds[1])*scale)/2)
    regions=[{'n':row['name'],'d':builder.svg_path(row.geometry,bounds,scale,offset)} for _,row in layer.iterrows()]
    data={'width':1600,'height':850,'geography_asof':'2021-11-01','source':SOURCE_URL,'source_sha256':SOURCE_SHA,'features':regions}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text('window.SBER_REGION_HOLOGRAM='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n')
    return len(regions)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent/'landing-common/regions-2021.js')
    args=parser.parse_args();print('Regions:',build(args.source,args.output))
