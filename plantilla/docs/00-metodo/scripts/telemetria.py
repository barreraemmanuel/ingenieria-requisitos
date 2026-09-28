#!/usr/bin/env python3
"""Eventos locales de uso y envío consentido a un receptor HTTP de loopback.

El agente muestra el cuerpo y el SHA-256 de ``preparar`` al dueño. Sólo tras una
decisión explícita sobre ese digest invoca ``confirmar``. El CLI no autentica al
dueño: el recibo identifica al actor sintético que operó el harness.
"""
import argparse
import base64
import datetime as dt
import hashlib
import http.client
import ipaddress
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from caja_negra import credencial_residual, redactar_incidente, seleccionar_incidentes


RAIZ = Path(__file__).resolve().parents[3]
SCHEMA = "telemetria-uso-v1"
BODY_SCHEMA = "telemetria-lote-v1"
FIELDS = frozenset(("schema", "id", "timestamp", "accion", "resultado"))
# Inventario de mutadores del parser de peticion.py; consultas quedan fuera.
ACCIONES = frozenset((
    "capturar", "desbloquear", "aclarar", "reclamar", "evaluar", "enlazar",
    "desenlazar", "marcar-proceso", "reencuadrar-orden", "reconciliar",
    "abrir-expres", "abrir-hotfix", "cerrar", "aparcar", "reanudar",
    "reabrir", "relacionar", "duplicar", "cancelar",
))
RESULTADOS = frozenset(("ok", "error"))
MAX_EVENTOS = 1000


def _base(repo):
    return Path(repo).resolve() / ".runtime" / "telemetria"


def _canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(data):
    def invalid(value):
        raise ValueError("JSON con número no finito")
    return json.loads(data, parse_constant=invalid)


def _write_once(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _write_replace(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _evento(row):
    if not isinstance(row, dict):
        raise ValueError("evento inválido: se esperaba objeto")
    projected = {key: row[key] for key in FIELDS if key in row}
    if set(projected) != FIELDS or projected["schema"] != SCHEMA:
        raise ValueError("evento con esquema o campos obligatorios inválidos")
    try:
        identity = uuid.UUID(projected["id"])
        if str(identity) != projected["id"]:
            raise ValueError("UUID no canónico")
        stamp = projected["timestamp"]
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if not stamp.endswith("Z") or when.utcoffset() != dt.timedelta(0):
            raise ValueError("fecha no UTC")
    except (TypeError, AttributeError, ValueError) as exc:
        raise ValueError("evento con UUID o UTC inválido") from exc
    if projected["accion"] not in ACCIONES or projected["resultado"] not in RESULTADOS:
        raise ValueError("evento con acción o resultado desconocido")
    # Caja negra transforma texto antes de exponerlo; la proyección descarta
    # campos arbitrarios que su redactor conserva por compatibilidad.
    clean = redactar_incidente(projected)
    if credencial_residual(_canon(clean).decode("utf-8")):
        raise ValueError("evento con credencial residual")
    return clean, len(row) - len(FIELDS)


def registrar(repo, accion, resultado):
    """Escribe sólo el vocabulario cerrado. El llamador contiene los errores de IO."""
    if accion not in ACCIONES or resultado not in RESULTADOS:
        raise ValueError("acción o resultado fuera del inventario")
    event = {"schema": SCHEMA, "id": str(uuid.uuid4()),
             "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
             "accion": accion, "resultado": resultado}
    clean, _ = _evento(event)
    path = _base(repo) / "eventos.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(_canon(clean) + b"\n")
        handle.flush()
    return clean


def _leer(repo):
    path = _base(repo) / "eventos.jsonl"
    if not path.is_file():
        return [], _sha(b""), 0
    raw = path.read_bytes()
    rows, omitted, seen = [], {}, set()
    try:
        for line in raw.splitlines():
            row = _json(line)
            # Reutilizar el selector exige validar duplicados en el origen entero.
            clean, count = _evento(row)
            if clean["id"] in seen:
                raise ValueError("IDs duplicados en el registro")
            seen.add(clean["id"])
            rows.append(clean)
            omitted[clean["id"]] = count
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("JSONL malformado; corregir el registro local") from exc
    return rows, _sha(raw), omitted


def listar_eventos(repo):
    rows, _, _ = _leer(repo)
    return rows


def _destino(url):
    if not isinstance(url, str) or any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise ValueError("destino inválido: se exige HTTP loopback")
    try:
        parsed = urlsplit(url)
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except (ValueError, TypeError) as exc:
        raise ValueError("destino inválido: se exige IP loopback literal y puerto") from exc
    if (not url.startswith("http://") or parsed.geturl() != url
            or parsed.scheme != "http" or parsed.username is not None or parsed.password is not None
            or parsed.fragment or parsed.query or not re.fullmatch(r"/[A-Za-z0-9_./-]*", parsed.path or "/")
            or str(address) not in ("127.0.0.1", "::1")
            or port is None or not 1 <= port <= 65535 or parsed.netloc !=
            (f"[{address}]:{port}" if address.version == 6 else f"{address}:{port}")):
        raise ValueError("destino inválido: se exige HTTP loopback literal y puerto")
    return parsed


def _paths(repo, digest):
    base = _base(repo)
    return base / "lotes" / (digest + ".json"), base / "lotes" / (digest + ".meta.json"), base / "reservas" / (digest + ".json"), base / "recibos" / (digest + ".json")


def _digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("digest SHA-256 inválido")


def preparar(repo, ids, destino):
    parsed = _destino(destino)
    ids = list(ids)
    if not ids or len(ids) > MAX_EVENTOS:
        raise ValueError("selecciona entre 1 y 1000 IDs completos")
    try:
        if len(set(ids)) != len(ids) or any(str(uuid.UUID(x)) != x for x in ids):
            raise ValueError("IDs repetidos o no canónicos")
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("selecciona UUID completos, únicos y existentes") from exc
    rows, source_sha, omitted = _leer(repo)
    lookup = {row["id"]: row for row in rows}
    if any(x not in lookup for x in ids):
        raise ValueError("ID inexistente; consulta listar y selecciona UUID completos")
    # El selector de caja negra se reutiliza después de validar, y aquí se
    # recupera el orden solicitado, que su API histórica no conserva.
    selected = seleccionar_incidentes(rows, ids)
    by_id = {row["id"]: row for row in selected}
    body = _canon({"schema": BODY_SCHEMA, "destino": destino,
                   "eventos": [by_id[x] for x in ids]})
    if credencial_residual(body.decode("utf-8")):
        raise ValueError("lote con credencial residual; corregir origen")
    digest = _sha(body)
    body_path, meta_path, reserve_path, receipt_path = _paths(repo, digest)
    if reserve_path.exists() or receipt_path.exists():
        raise ValueError("digest enviado o incierto; no se puede preparar de nuevo")
    if body_path.exists():
        if body_path.read_bytes() != body:
            raise ValueError("colisión de digest del lote")
    else:
        _write_once(body_path, body)
    meta = {"schema": "telemetria-preparacion-v1", "sha256": digest,
            "origen_sha256": source_sha, "ids": ids, "destino": destino,
            "estado": "preparado"}
    _write_replace(meta_path, _canon(meta))
    # La salida cuenta campos omitidos sólo del snapshot ya validado.
    omitted = sum(omitted[x] for x in ids)
    return {"sha256": digest, "cuerpo": body, "ids": ids, "destino": destino,
            "cantidad": len(ids), "omitidos": omitted}


def _preflight(repo, digest):
    _digest(digest)
    body_path, meta_path, reserve_path, receipt_path = _paths(repo, digest)
    if reserve_path.exists() or receipt_path.exists():
        raise ValueError("lote enviado o incierto; reconciliar sin retransmitir")
    try:
        body = body_path.read_bytes()
        meta = _json(meta_path.read_bytes())
        source = (_base(repo) / "eventos.jsonl").read_bytes()
        parsed_body = _json(body)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("preparación incompleta; preparar de nuevo") from exc
    if (not isinstance(meta, dict) or not isinstance(parsed_body, dict)
            or not isinstance(parsed_body.get("eventos"), list)
            or any(not isinstance(x, dict) for x in parsed_body["eventos"])
            or _sha(body) != digest or meta.get("sha256") != digest
            or meta.get("origen_sha256") != _sha(source)
            or meta.get("destino") != parsed_body.get("destino")
            or [x.get("id") for x in parsed_body.get("eventos", [])] != meta.get("ids")
            or _canon(parsed_body) != body):
        raise ValueError("lote, selección, origen o destino cambiaron; preparar de nuevo")
    _destino(meta["destino"])
    return body, meta


def reservar(repo, digest, actor):
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 100 or any(ord(x) < 32 for x in actor):
        raise ValueError("identidad de actor sintético inválida")
    body, meta = _preflight(repo, digest)
    _, _, reserve_path, _ = _paths(repo, digest)
    try:
        _write_once(reserve_path, _canon({"schema": "telemetria-reserva-v1", "sha256": digest,
                                         "destino": meta["destino"], "actor": actor,
                                         "estado": "incierto"}))
    except FileExistsError as exc:
        raise ValueError("lote ya reservado; no retransmitir") from exc
    return body, meta


def confirmar(repo, digest, decision, actor):
    # La autorización se comprueba antes incluso de reservar el digest.
    if decision != "si":
        raise ValueError("envío rechazado o sin consentimiento explícito")
    body, meta = reservar(repo, digest, actor)
    parsed = _destino(meta["destino"])
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection.request("POST", path, body=body,
                           headers={"Content-Type": "application/json; charset=utf-8",
                                    "X-Body-SHA256": digest})
        response = connection.getresponse()
        answer = response.read(4096)
        reported = _json(answer)
        if not 200 <= response.status < 300 or not isinstance(reported, dict) or reported.get("sha256") != digest:
            raise ValueError("receptor sin confirmación del digest exacto")
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError, http.client.HTTPException) as exc:
        raise ValueError("entrega incierta; reconciliar con recibo observado, sin retransmitir") from exc
    finally:
        connection.close()
    receipt = {"schema": "telemetria-recibo-v1", "sha256": digest,
               "destino": meta["destino"], "actor": actor, "estado": "compartido",
               "origen": "respuesta-http"}
    _, _, _, receipt_path = _paths(repo, digest)
    _write_once(receipt_path, _canon(receipt))
    return receipt


def reconciliar(repo, digest, observado):
    _digest(digest)
    body_path, meta_path, reserve_path, receipt_path = _paths(repo, digest)
    if not reserve_path.is_file() or receipt_path.exists():
        raise ValueError("no existe entrega incierta para reconciliar")
    try:
        body = body_path.read_bytes()
        meta = _json(meta_path.read_bytes())
        reservation = _json(reserve_path.read_bytes())
        observed = _json(Path(observado).read_bytes())
        if not isinstance(meta, dict) or not isinstance(reservation, dict) or not isinstance(observed, dict):
            raise ValueError("recibo no es un objeto")
        seen = base64.b64decode(observed["cuerpo_base64"], validate=True)
        if not isinstance(reservation.get("actor"), str):
            raise ValueError("reserva incompleta")
    except (OSError, ValueError, KeyError, TypeError, base64.binascii.Error) as exc:
        raise ValueError("recibo observado incompleto; entrega sigue incierta") from exc
    if (seen != body or _sha(body) != digest or observed.get("sha256") != digest
            or observed.get("schema") != "telemetria-recepcion-observada-v1"
            or observed.get("metodo") != "POST"
            or type(observed.get("http_status")) is not int
            or not 200 <= observed["http_status"] < 300
            or observed.get("destino") != meta.get("destino")
            or reservation.get("sha256") != digest):
        raise ValueError("recibo observado discrepante; entrega sigue incierta")
    receipt = {"schema": "telemetria-recibo-v1", "sha256": digest,
               "destino": meta["destino"], "actor": reservation["actor"],
               "estado": "compartido", "origen": "recibo-observado"}
    _write_once(receipt_path, _canon(receipt))
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=RAIZ, help="workspace local")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("listar", help="muestra sólo campos permitidos y cuenta omisiones")
    p = sub.add_parser("preparar", help="guarda y muestra bytes exactos, IDs y digest; no conecta")
    p.add_argument("--id", action="append", required=True, dest="ids", help="UUID completo; repetir para ordenar")
    p.add_argument("--destino", required=True, help="HTTP loopback literal y puerto")
    p = sub.add_parser("confirmar", help="envía una vez tras decisión explícita sobre el digest mostrado")
    p.add_argument("--sha256", required=True)
    p.add_argument("--decision", required=True, choices=("si", "no"))
    p.add_argument("--actor", required=True, help="identidad del actor sintético; no autentica al dueño")
    p = sub.add_parser("reconciliar", help="coteja recibo observado local; nunca conecta")
    p.add_argument("--sha256", required=True)
    p.add_argument("--recibo", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.comando == "listar":
            rows, _, omitted = _leer(args.repo)
            print(f"{len(rows)} eventos; campos privados omitidos: {sum(omitted.values())}")
            for row in rows:
                print(_canon(row).decode("utf-8"))
        elif args.comando == "preparar":
            result = preparar(args.repo, args.ids, args.destino)
            print(f"{result['cantidad']} eventos; campos privados omitidos: {result['omitidos']}")
            print("IDs: " + ", ".join(result["ids"]))
            print("Destino: " + result["destino"])
            print("SHA-256: " + result["sha256"])
            print(result["cuerpo"].decode("utf-8"))
        elif args.comando == "confirmar":
            print(_canon(confirmar(args.repo, args.sha256, args.decision, args.actor)).decode("utf-8"))
        else:
            print(_canon(reconciliar(args.repo, args.sha256, args.recibo)).decode("utf-8"))
        return 0
    except (ValueError, OSError) as exc:
        # Los mensajes de IO pueden contener rutas privadas; nunca se copian.
        reason = str(exc) if isinstance(exc, ValueError) else "no se pudo leer o guardar el estado local"
        print(f"FAIL telemetria: {reason}; salida: python3 docs/00-metodo/scripts/telemetria.py --help", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
