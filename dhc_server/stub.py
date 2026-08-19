"""Response contoh untuk stub mode (API contract sect. 7).

Ini SALINAN PERSIS contoh di kontrak, supaya app bisa membuktikan handshake-nya
benar sebelum model asli dipasang. Nilainya berasal dari pasien 2018.08.

Kalau bentuk response berubah, ubah di sini juga -- ada test yang memastikan stub
dan hasil asli punya struktur yang sama, jadi stub yang basi akan ketahuan.
"""

from __future__ import annotations

from typing import Any, Dict

from dhc_pipeline.report import ENGINE_VERSION


def stub_response(patient_id: str | None = "2018.08") -> Dict[str, Any]:
    return {
        "patient_id": patient_id,
        "engine_version": f"{ENGINE_VERSION} (stub)",
        "overjet": {
            "value": 0.5,
            "label": "possible excess overjet",
            "side": "right",
            "reliable": True,
            "warnings": [],
        },
        "overbite": {
            "value": 0.23,
            "label": "possible normal overbite",
            "side": "right",
            "reliable": True,
            "warnings": [],
        },
        "anterior_crossbite": {
            "value": 0.5,
            "label": "no anterior crossbite",
            "side": "right",
            "reliable": True,
            "warnings": [],
        },
        "angle": {
            "side": "left",
            "molar": {
                "value": None,
                "label": None,
                "side": None,
                "reliable": False,
                "warnings": ["molar position not found"],
            },
            "canine": {
                "value": -0.61,
                "label": "resembles Class III",
                "side": "left",
                "reliable": True,
                "warnings": [],
            },
            "disagreement": False,
        },
        "crossbite_posterior": {
            "label": "possible posterior crossbite",
            "reliable": True,
            "flagged": [{"side": "left", "posisi": 1, "ratio": 0.10}],
            "warnings": [],
        },
        "missing": {
            "occlusal_gaps": 0,
            "frontal_gaps": 1,
            "disagreement": True,
            "reliable": False,
            "warnings": [
                "occlusal and frontal counts disagree; occlusal is the primary source "
                "but a large difference needs manual review"
            ],
        },
        "crowding": {
            "upper": {
                "sum": 1.16,
                "label": "possible crowding",
                "flagged_teeth": [4, 5, 6],
                "reliable": True,
                "warnings": [],
            },
            "lower": {
                "sum": 1.40,
                "label": "possible crowding",
                "flagged_teeth": [6, 7, 8],
                "reliable": False,
                "warnings": [
                    "lower-arch threshold is not yet validated (calibrated on upper arch only)"
                ],
            },
        },
        # Contoh overlay NYATA (dipangkas). Sengaja GABUNGAN dua pasien supaya
        # setiap `role` terwakili: sebagian besar dari 2018.08, ditambah satu
        # bentuk `rejected` dari 2018.05 lateral kanan -- serpihan di luar mulut
        # yang dulu terpilih jadi anchor insisivus dan menghasilkan overjet 9.33.
        # Tujuannya supaya app bisa menguji renderer-nya lengkap
        # Response asli mengirim ~80-100 bentuk; di sini sengaja hanya beberapa.
        "overlays": {
            "frontal": {"shapes": [
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.56, 0.2778], [0.535, 0.3153], [0.5337, 0.3604], [0.56, 0.411], [0.5925, 0.4073], [0.6075, 0.3941], [0.6162, 0.3735], [0.6162, 0.3266], [0.61, 0.2928], [0.5962, 0.2778]]},
                {"kind": "polygon", "role": "flagged", "label": None,
                 "params": ["crossbite_posterior"],
                 "points": [[0.3975, 0.2853], [0.3587, 0.2853], [0.3313, 0.3322], [0.33, 0.4167], [0.3388, 0.4373], [0.3625, 0.4467], [0.3762, 0.4148], [0.42, 0.3904], [0.4275, 0.3679], [0.4275, 0.3341]]},
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.6413, 0.2121], [0.6162, 0.2459], [0.6162, 0.2984], [0.6425, 0.3191], [0.66, 0.3209], [0.6775, 0.2872], [0.6775, 0.2384], [0.6662, 0.2121]]},
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.2562, 0.3435], [0.2362, 0.3491], [0.225, 0.3416], [0.1925, 0.3416], [0.18, 0.3622], [0.18, 0.426], [0.2075, 0.4955], [0.2275, 0.488], [0.2562, 0.4354]]},
                {"kind": "box", "role": "gap", "label": None,
                 "params": ["missing"],
                 "points": [[0.1425, 0.3416], [0.18, 0.5124]]},
            ]},
            "lateral_kanan": {"shapes": [
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.7588, 0.3228], [0.7588, 0.3791], [0.7713, 0.4091], [0.7812, 0.411], [0.7862, 0.4073], [0.7887, 0.3998], [0.7887, 0.3735], [0.7775, 0.3228]]},
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.73, 0.3585], [0.7188, 0.381], [0.7188, 0.4091], [0.7312, 0.4167], [0.7412, 0.4298], [0.7638, 0.4298], [0.7625, 0.4223], [0.7663, 0.3998], [0.7538, 0.3604]]},
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.7125, 0.3697], [0.7013, 0.3528], [0.6825, 0.3528], [0.66, 0.3754], [0.6575, 0.3829], [0.6575, 0.4223], [0.6625, 0.4242], [0.6712, 0.4091], [0.6825, 0.4035], [0.7113, 0.4035], [0.715, 0.3848]]},
                {"kind": "box", "role": "anchor", "label": "distal",
                 "params": ["angle"],
                 "points": [[0.2047, 0.4401], [0.3054, 0.5337]]},
                {"kind": "box", "role": "anchor", "label": "canine",
                 "params": ["angle"],
                 "points": [[0.4147, 0.3465], [0.5117, 0.5027]]},
                {"kind": "box", "role": "reference", "label": "incisor",
                 "params": ["overjet", "overbite", "anterior_crossbite"],
                 "points": [[0.5838, 0.3303], [0.6538, 0.4692]]},
                {"kind": "box", "role": "reference", "label": "incisor",
                 "params": ["overjet", "overbite", "anterior_crossbite"],
                 "points": [[0.555, 0.4373], [0.6187, 0.5593]]},
                {"kind": "box", "role": "reference", "label": "canine",
                 "params": ["angle"],
                 "points": [[0.4187, 0.3566], [0.5038, 0.4974]]},
                {"kind": "line", "role": "measurement", "label": None,
                 "params": ["overjet", "overbite", "anterior_crossbite"],
                 "points": [[0.5838, 0.4533], [0.555, 0.4533]]},
                {"kind": "line", "role": "measurement", "label": None,
                 "params": ["overjet", "overbite", "anterior_crossbite"],
                 "points": [[0.6028, 0.4692], [0.6028, 0.4373]]},
                {"kind": "polygon", "role": "rejected", "label": None,
                 "params": ["overjet", "overbite", "anterior_crossbite", "angle"],
                 "points": [[0.9987, 0.2271], [0.9887, 0.2271], [0.98, 0.2421], [0.9725, 0.2459], [0.9725, 0.2815], [0.975, 0.2853], [0.9987, 0.2872]]},
            ]},
            "lateral_kiri": {"shapes": [
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.5875, 0.4486], [0.5863, 0.4392], [0.5412, 0.4317], [0.515, 0.4486], [0.5075, 0.4354], [0.5075, 0.3941], [0.545, 0.3735], [0.5075, 0.3866], [0.515, 0.3697], [0.5075, 0.3547], [0.5075, 0.3866], [0.5775, 0.3547], [0.6025, 0.3547], [0.6025, 0.381], [0.5875, 0.426], [0.5412, 0.4317], [0.5863, 0.4392], [0.5788, 0.4486]]},
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.5188, 0.3059], [0.485, 0.3059], [0.46, 0.3378], [0.46, 0.3697], [0.4638, 0.3791], [0.49, 0.3998], [0.5013, 0.3998], [0.525, 0.3679], [0.53, 0.351], [0.53, 0.3228]]},
                {"kind": "box", "role": "anchor", "label": "canine",
                 "params": ["angle"],
                 "points": [[0.4973, 0.3352], [0.6133, 0.4902]]},
                {"kind": "box", "role": "anchor", "label": "canine",
                 "params": ["angle"],
                 "points": [[0.4492, 0.4093], [0.5231, 0.5288]]},
                {"kind": "box", "role": "reference", "label": "canine",
                 "params": ["angle"],
                 "points": [[0.5075, 0.3547], [0.6025, 0.4486]]},
                {"kind": "box", "role": "reference", "label": "canine",
                 "params": ["angle"],
                 "points": [[0.45, 0.4204], [0.5225, 0.5161]]},
            ]},
            "oklusal_atas": {"shapes": [
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.2625, 0.61], [0.2463, 0.6381], [0.2412, 0.732], [0.2887, 0.7939], [0.3125, 0.7995], [0.355, 0.7207], [0.3525, 0.6719], [0.3225, 0.6325], [0.2825, 0.61]]},
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.3025, 0.4298], [0.3013, 0.4899], [0.31, 0.5143], [0.3438, 0.5368], [0.3688, 0.5405], [0.3887, 0.533], [0.4013, 0.5124], [0.4013, 0.4598], [0.3887, 0.4392], [0.365, 0.4185], [0.3187, 0.4129]]},
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.2738, 0.5349], [0.2763, 0.6025], [0.3262, 0.6306], [0.3462, 0.6306], [0.3562, 0.6231], [0.3675, 0.595], [0.3675, 0.5743], [0.3525, 0.5443], [0.3075, 0.5124], [0.285, 0.5124]]},
                {"kind": "polygon", "role": "flagged", "label": "6",
                 "params": ["crowding"],
                 "points": [[0.4613, 0.2027], [0.4613, 0.2402], [0.49, 0.3022], [0.5, 0.3097], [0.5213, 0.3097], [0.5487, 0.2853], [0.5537, 0.2684], [0.5537, 0.2421], [0.5375, 0.2121], [0.505, 0.1952], [0.4663, 0.1952]]},
                {"kind": "polygon", "role": "flagged", "label": "5",
                 "params": ["crowding"],
                 "points": [[0.4625, 0.2459], [0.42, 0.2496], [0.3925, 0.274], [0.3925, 0.304], [0.4112, 0.3416], [0.4487, 0.3453], [0.4737, 0.3228], [0.4787, 0.2853]]},
                {"kind": "line", "role": "archCurve", "label": None,
                 "params": [],
                 "points": [[0.2981, 0.6442], [0.3201, 0.572], [0.342, 0.5064], [0.3644, 0.4462], [0.3863, 0.3939], [0.4088, 0.3473], [0.4307, 0.3084], [0.4531, 0.2755], [0.4751, 0.25], [0.497, 0.2311], [0.5194, 0.2186], [0.5413, 0.213], [0.5638, 0.2142], [0.5857, 0.222], [0.6081, 0.2368], [0.6301, 0.258], [0.652, 0.2857], [0.6744, 0.321], [0.6963, 0.3621], [0.7188, 0.411], [0.7407, 0.4655], [0.7631, 0.5281], [0.7851, 0.596], [0.8075, 0.6722]]},
            ]},
            "oklusal_bawah": {"shapes": [
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.2525, 0.1164], [0.2338, 0.1501], [0.2362, 0.2327], [0.265, 0.2571], [0.3025, 0.2515], [0.3075, 0.2233], [0.29, 0.1107]]},
                {"kind": "polygon", "role": "tooth", "label": None,
                 "params": [],
                 "points": [[0.5788, 0.4655], [0.5625, 0.4842], [0.555, 0.5049], [0.555, 0.5387], [0.5675, 0.5649], [0.5813, 0.5799], [0.6062, 0.5837], [0.6263, 0.5555], [0.6275, 0.5218], [0.6225, 0.488], [0.6087, 0.4655]]},
                {"kind": "polygon", "role": "flagged", "label": "8",
                 "params": ["crowding"],
                 "points": [[0.4725, 0.6212], [0.465, 0.6325], [0.465, 0.6869], [0.475, 0.7038], [0.4812, 0.7076], [0.4963, 0.7038], [0.51, 0.6926], [0.5213, 0.6644], [0.5213, 0.6419], [0.5038, 0.6212]]},
                {"kind": "polygon", "role": "flagged", "label": "7",
                 "params": ["crowding"],
                 "points": [[0.4137, 0.6306], [0.4137, 0.6869], [0.4212, 0.7001], [0.435, 0.7076], [0.4512, 0.7076], [0.4625, 0.7001], [0.4638, 0.6513], [0.4525, 0.6175], [0.4288, 0.6175], [0.4225, 0.6269]]},
                {"kind": "line", "role": "archCurve", "label": None,
                 "params": [],
                 "points": [[0.2706, 0.3265], [0.2906, 0.3884], [0.3106, 0.444], [0.3311, 0.4944], [0.351, 0.5371], [0.3715, 0.5743], [0.3915, 0.6043], [0.4119, 0.6283], [0.4319, 0.6454], [0.4519, 0.6562], [0.4724, 0.6606], [0.4924, 0.6585], [0.5128, 0.6498], [0.5328, 0.6349], [0.5532, 0.613], [0.5732, 0.5852], [0.5932, 0.5511], [0.6137, 0.5096], [0.6337, 0.4627], [0.6541, 0.4081], [0.6741, 0.3483], [0.6946, 0.2805], [0.7145, 0.2079], [0.735, 0.127]]},
            ]},
        },
    }
