import requests

def test_all():
    scenarios = ['A', 'B', 'C', 'D', 'E']
    formats = ['JPEG', 'PNG', 'PDF', 'ZIP']
    for sc in scenarios:
        for ft in formats:
            res = requests.post(
                'http://127.0.0.1:8000/api/v1/reconstruction/scenarios/run',
                data={'scenario_id': sc, 'format_type': ft}
            )
            assert res.status_code == 200, f"Failed {sc}-{ft}: {res.text}"
            data = res.json()
            eval_data = data['evaluation']
            rep = data['report']
            val = data['validation']
            print(f"[{sc}] {ft:4s} -> Status: {rep['final_status']:10s} | "
                  f"ByteAcc: {eval_data['byte_level_accuracy']*100:6.1f}% | "
                  f"OrderAcc: {eval_data['fragment_ordering_accuracy']*100:6.1f}% | "
                  f"FormatValid: {val['format_valid']}")

if __name__ == '__main__':
    test_all()
