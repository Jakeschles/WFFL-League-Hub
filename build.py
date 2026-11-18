import json, sys, pathlib
here = pathlib.Path(__file__).parent
data = json.loads((here/'data.json').read_text())
tpl = (here/'template.html').read_text()
blob = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
(here/'index.html').write_text(tpl.replace('/*DATA*/', blob))
print('built index.html', len(blob))
