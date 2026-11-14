# Tests for bin/route-keys.py: python3 -m unittest discover tests
# (needs route-keys, as routes.yml installs it).
import copy, gzip, importlib.util, json, os, tempfile, unittest

from route_keys import decode

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('route_keys_step', os.path.join(HERE, '..', 'bin', 'route-keys.py'))
step = importlib.util.module_from_spec(spec)
spec.loader.exec_module(step)

# From route-keys' vectors/v1.json (v0.1.0): the line, its shape and its key.
EAST = [[-116.2, 51.4], [-116.1856, 51.4]]                     # w
EAST_KEY = '1EsA3CLAwBJBHADABAACCCECGCI.wJlPb18DmiE'
REPEATED = [[-116.2, 51.4], [-116.2, 51.4], [-116.19, 51.405], [-116.19, 51.405], [-116.18, 51.41]]  # w
REPEATED_KEY = '1EsA3CTAwFKDIBGAAACCDEFGLGH.NQ5n99Gtcak'
NZ = [[168.1265, -44.7244], [168.1301, -44.7187], [168.1356, -44.7121], [168.142, -44.708]]  # b
NZ_KEY = '12oOskpgbBPBLBHBDBABEAICOES.yik1Umoa2wo'
STOP = [[-112.25456, 36.8302], [-112.25467, 36.83061], [-112.25456, 36.8302]]  # b (163123/stop/2)
STOP_KEY = '1KZRunWAbAA.MrLIYM27FRv'
LOOP = [[-116.2, 51.4], [-116.19, 51.405], [-116.18, 51.4], [-116.2, 51.4]]


def route(line, **kw):
    return {'line': line, 'km': 1.0, 'key': 'name|based', **kw}


DOC_A = {
    'park': {'id': '1', 'name': 'Älpine Park'},
    'day_hikes': [
        {'kind': 'out-and-back', 'name': 'NZ', 'route': route(NZ)},
        {'kind': 'one-way', 'route': route(EAST)},
        {'kind': 'loop', 'route': route(LOOP)},
        {'kind': 'out-and-back', 'route': route([[-116.2, 51.4]])},  # too short
    ],
    'stops': [{'name': 'Lookout', 'route': route(STOP)}],
    'base_camps': [{'camp': 'Camp', 'approach': route(REPEATED),
                    'hikes': [{'kind': 'out-and-back', 'route': route(NZ)}]}],
    'point_to_points': [{'kind': 'one-way', 'from': 'A', 'to': 'B', 'route': route(EAST)}],
}
DOC_B = {'park': {'id': '2', 'name': 'B'}, 'day_hikes': [{'kind': 'loop', 'route': route([])}]}


def gz(doc):
    return gzip.compress(json.dumps(doc).encode(), mtime=0)


class RouteKeysTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.dir = self.tmp.name
        os.mkdir(os.path.join(d, 'parks'))
        a, b = gz(DOC_A), gz(DOC_B)
        cards = gzip.compress(b'{"1":{"top":"NZ"}}', mtime=0)
        with open(os.path.join(d, 'routes.bin'), 'wb') as f:
            f.write(a + b + cards)
        # Park 1 is also "1b" (a twin: same slice, no file of its own); as
        # hike-paths.py leaves it, with cards after the parks.
        index = {'bundle': 'routes.bin',
                 'parks': {'2': [len(a), len(b)], '1': [0, len(a)], '1b': [0, len(a)]},
                 'cards': {'canada/alberta': [len(a) + len(b), len(cards)]},
                 'paths': {'1': 'canada/alberta/alpine-park'}}
        json.dump(index, open(os.path.join(d, 'index.json'), 'w'))
        for doc in (DOC_A, DOC_B):
            json.dump(doc, open(os.path.join(d, 'parks', f"{doc['park']['id']}.json"), 'w'))

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        index = json.load(open(os.path.join(self.dir, 'index.json')))
        bundle = open(os.path.join(self.dir, 'routes.bin'), 'rb').read()
        sl = lambda at: gzip.decompress(bundle[at[0]:at[0] + at[1]])
        return index, bundle, sl

    def test_keys(self):
        self.assertEqual(step.main(self.dir), (7, 2))
        index, _, sl = self.read()
        doc = json.loads(sl(index['parks']['1']))
        dh = doc['day_hikes']
        self.assertEqual(dh[0]['route']['route_key'], NZ_KEY)
        self.assertEqual(dh[1]['route']['route_key'], EAST_KEY)
        self.assertEqual(decode(dh[2]['route']['route_key']).shape, 'p')
        self.assertNotIn('route_key', dh[3]['route'])
        self.assertEqual(doc['stops'][0]['route']['route_key'], STOP_KEY)
        self.assertEqual(doc['base_camps'][0]['approach']['route_key'], REPEATED_KEY)
        self.assertEqual(doc['base_camps'][0]['hikes'][0]['route']['route_key'], NZ_KEY)
        self.assertEqual(doc['point_to_points'][0]['route']['route_key'], EAST_KEY)
        # routes' own name-based key is left alone, and so is the rest.
        self.assertEqual(dh[0]['route']['key'], 'name|based')
        self.assertEqual(doc['park']['name'], 'Älpine Park')
        self.assertNotIn('route_key', json.loads(sl(index['parks']['2']))['day_hikes'][0]['route'])

    def test_offsets_and_files(self):
        step.main(self.dir)
        index, bundle, sl = self.read()
        self.assertEqual(index['parks']['1'], index['parks']['1b'])
        self.assertEqual(set(index['parks']), {'1', '1b', '2'})
        self.assertEqual(index['paths'], {'1': 'canada/alberta/alpine-park'})
        self.assertEqual(json.loads(sl(index['cards']['canada/alberta'])), {'1': {'top': 'NZ'}})
        ends = sorted(at[0] + at[1] for v in (index['parks'], index['cards']) for at in v.values())
        self.assertEqual(ends[-1], len(bundle))
        # parks/<id>.json is the bundle's document; no file for the twin.
        for pid in ('1', '2'):
            self.assertEqual(open(os.path.join(self.dir, 'parks', f'{pid}.json'), 'rb').read(),
                             sl(index['parks'][pid]))
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'parks', '1b.json')))
        self.assertEqual(sorted(os.listdir(self.dir)), ['index.json', 'parks', 'routes.bin'])

    def test_idempotent(self):
        step.main(self.dir)
        first = self.read()[:2]
        parks = {f: open(os.path.join(self.dir, 'parks', f), 'rb').read() for f in os.listdir(os.path.join(self.dir, 'parks'))}
        self.assertEqual(step.main(self.dir), (7, 2))
        self.assertEqual(self.read()[:2], first)
        for f, body in parks.items():
            self.assertEqual(open(os.path.join(self.dir, 'parks', f), 'rb').read(), body)

    def test_stale_keys_replaced(self):
        # A key from before (wrong, or on a line now too short) is recomputed.
        doc = copy.deepcopy(DOC_A)
        doc['day_hikes'][0]['route']['route_key'] = 'stale'
        doc['day_hikes'][3]['route']['route_key'] = 'stale'
        a = gz(doc)
        with open(os.path.join(self.dir, 'routes.bin'), 'wb') as f:
            f.write(a)
        json.dump({'bundle': 'routes.bin', 'parks': {'1': [0, len(a)]}}, open(os.path.join(self.dir, 'index.json'), 'w'))
        step.main(self.dir)
        index, _, sl = self.read()
        dh = json.loads(sl(index['parks']['1']))['day_hikes']
        self.assertEqual(dh[0]['route']['route_key'], NZ_KEY)
        self.assertNotIn('route_key', dh[3]['route'])

    def test_empty(self):
        # No parks (a small preview): routes.yml writes an empty bundle.
        open(os.path.join(self.dir, 'routes.bin'), 'wb').close()
        json.dump({'bundle': 'routes.bin', 'parks': {}}, open(os.path.join(self.dir, 'index.json'), 'w'))
        self.assertEqual(step.main(self.dir), (0, 0))
        self.assertEqual(self.read()[0], {'bundle': 'routes.bin', 'parks': {}})


if __name__ == '__main__':
    unittest.main()
