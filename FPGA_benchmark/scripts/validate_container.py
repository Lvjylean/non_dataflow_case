"""Validate recovered U250 container metadata without claiming board execution."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'reports'
for name in sys.argv[1:]:
    run = root / name
    count = 6 if name.startswith('cnna6') else 1
    def read(filename):
        return json.loads((run / filename).read_text())
    memory = read('MEM_TOPOLOGY.json')['mem_topology']['m_mem_data']
    ips = read('IP_LAYOUT.json')['ip_layout']['m_ip_data']
    kernels = [(i, ip) for i, ip in enumerate(ips) if ip['m_type'] == 'IP_KERNEL']
    connections = read('CONNECTIVITY.json')['connectivity']['m_connection']
    clocks = read('CLOCK_FREQ_TOPOLOGY.json')['clock_freq_topology']['m_clock_freq']
    actual = {(int(c['m_ip_layout_index']), int(c['arg_index']), int(c['mem_data_index'])) for c in connections}
    expected = {(i, a, 2 if count == 1 or k < 3 else 3)
                for k, (i, ip) in enumerate(kernels) for a in range(1 if count == 1 else 5)}
    checks = {
        'exit_zero': (run / 'exit_code').read_text().strip() == '0',
        'kernel_count': len(kernels) == count,
        'connectivity_exact': actual == expected and len(connections) == len(expected),
        'ddr_high_addresses': int(memory[2]['m_base_address'], 16) == 0x6000000000 and int(memory[3]['m_base_address'], 16) == 0x7000000000,
        'address_window_covers_used_banks': all(int(m['m_base_address'], 16) + int(m['m_sizeKB'], 16) * 1024 <= 2**40 for m in memory if m['m_used'] == '1'),
        'data_clock_100_mhz': any(c['m_type'] == 'DATA' and float(c['m_freq_Mhz']) == 100 for c in clocks),
        'platform_interface': read('PARTITION_METADATA.json')['partition_metadata']['interfaces'] == [{'interface_uuid': 'a8880c2311a2a42b5fb76899d385acee'}],
        'payload_compared': (run / 'container_validation.tsv').read_text().strip() == 'container_bitstream_matches_source\t1',
    }
    result = {'run': name, 'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
              'scope': 'Container metadata/payload consistency only; physical signoff and board validation are separate.'}
    (run / 'container_metadata_validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)
