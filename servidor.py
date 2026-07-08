import sqlite3
import os
import re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from fastapi.responses import FileResponse
import libsql_client

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Ruta local que usaremos SOLO para subir tu info inicial a la nube
LOCAL_DB_PATH = os.path.join(BASE_DIR, "farmacia_hospital.db")

# Credenciales seguras cargadas desde Render
TURSO_URL = os.getenv("TURSO_URL")
TURSO_TOKEN = os.getenv("TURSO_TOKEN")

def get_db():
    if not TURSO_URL or not TURSO_TOKEN:
        raise Exception("Faltan las variables TURSO_URL y TURSO_TOKEN en Render.")
    return libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)

def inicializar_db():
    if not TURSO_URL or not TURSO_TOKEN:
        return
    try:
        with get_db() as client:
            client.execute("""CREATE TABLE IF NOT EXISTS usuarios (usuario TEXT PRIMARY KEY, password TEXT, rol TEXT)""")
            client.execute("""CREATE TABLE IF NOT EXISTS pacientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, edad TEXT, fecha_ingreso TEXT, fecha_egreso TEXT, medico TEXT)""")
            client.execute("""CREATE TABLE IF NOT EXISTS habitaciones (numero TEXT PRIMARY KEY, tipo TEXT, estado TEXT, paciente_id INTEGER, color TEXT)""")
            client.execute("""
                CREATE TABLE IF NOT EXISTS consumos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, paciente_id INTEGER, nombre_medicamento TEXT, presentacion TEXT,
                    cantidad REAL, precio_base REAL, precio_final REAL, total_articulo REAL, fecha_registro TEXT, registrado_por TEXT,
                    autorizado_por TEXT DEFAULT NULL, fecha_modificacion TEXT DEFAULT NULL
                )
            """)
            client.execute("""CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT)""")

            client.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('PIN_MAESTRO', '1234')") 
            for u, p, r in [("admin", "admin123", "administrador"), ("farmacia", "farma123", "farmacia"), ("recepcion", "recep123", "recepcion")]:
                client.execute("INSERT OR IGNORE INTO usuarios (usuario, password, rol) VALUES (?, ?, ?)", [u, p, r])
                
            habitaciones_base = [
                ("Habitación 1", "Habitación"), ("Habitación 2", "Habitación"), ("Habitación 3", "Habitación"),
                ("Habitación 4", "Habitación"), ("Habitación 5", "Habitación"), ("Habitación 7", "Habitación"),
                ("Habitación 8", "Habitación"), ("Habitación 9", "Habitación"), ("Habitación 10", "Habitación"),
                ("Habitación 11", "Habitación"), ("Habitación 12", "Habitación"), ("Habitación 13", "Habitación"),
                ("Habitación 15", "Habitación"), ("Valoración", "Urgencias"),
                ("Incubadora 1", "Incubadora"), ("Incubadora 2", "Incubadora"),
                ("Consultorio 1", "Consultorio"), ("Consultorio 2", "Consultorio"), ("Consultorio 3", "Consultorio")
            ]
            for hab, tipo in habitaciones_base:
                client.execute("INSERT OR IGNORE INTO habitaciones (numero, tipo, estado, paciente_id) VALUES (?, ?, 'LIBRE', NULL)", [hab, tipo])
    except Exception:
        pass

inicializar_db()

class LoginReq(BaseModel): usuario: str; password: str
class OcuparReq(BaseModel): numero_hab: str; nombre_paciente: str; edad: str; medico: str; fecha_ingreso: str = ""
class EditPacReq(BaseModel): id_paciente: int; nombre: str; edad: str; medico: str; fecha_ingreso: str = ""
class MedReq(BaseModel): paciente_id: int; nombre_med: str; presentacion: str; cantidad: float; precio_base: float; registrado_por: str
class PassReq(BaseModel): usuario_a_cambiar: str; nueva_password: str
class HabReq(BaseModel): numero: str; tipo: str
class EditReq(BaseModel): id_consumo: int; nueva_cantidad: float; nuevo_precio: float; pin_autorizacion: str
class PinReq(BaseModel): nuevo_pin: str

def natural_sort_key(hab):
    orden_tipo = {"Habitación": 1, "Suite": 2, "Incubadora": 3, "Urgencias": 4, "Consultorio": 5}
    tipo_val = orden_tipo.get(hab["tipo"], 99)
    partes_num = [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', hab["numero"])]
    return (tipo_val, partes_num)

@app.get("/")
def pagina_principal():
    ruta_index = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(ruta_index): return FileResponse(ruta_index)
    return {"error": "index.html no encontrado"}

@app.get("/logo")
def obtener_logo():
    ruta_logo = os.path.join(BASE_DIR, "logo fatima.jpg")
    if os.path.exists(ruta_logo): return FileResponse(ruta_logo)
    return {"error": "Logo no encontrado"}

@app.post("/login")
def login(req: LoginReq):
    with get_db() as client:
        rs = client.execute("SELECT rol FROM usuarios WHERE usuario = ? AND password = ?", [req.usuario.strip(), req.password.strip()])
        if rs.rows:
            return {"status": "ok", "rol": rs.rows[0][0], "usuario": req.usuario}
    raise HTTPException(status_code=401, detail="Error")

@app.get("/habitaciones")
def obtener_habitaciones():
    with get_db() as client:
        rs = client.execute("SELECT h.numero, h.estado, h.paciente_id, h.tipo, p.nombre, p.edad, p.fecha_ingreso, p.medico FROM habitaciones h LEFT JOIN pacientes p ON h.paciente_id = p.id")
        lista = [{"numero": f[0], "estado": f[1], "paciente_id": f[2], "tipo": f[3], "nombre": f[4], "edad": f[5], "fecha_ingreso": f[6], "medico": f[7]} for f in rs.rows]
    lista.sort(key=natural_sort_key) 
    return lista

@app.post("/agregar-habitacion")
def agregar_hab(req: HabReq):
    with get_db() as client:
        client.execute("INSERT OR IGNORE INTO habitaciones (numero, tipo, estado) VALUES (?, ?, 'LIBRE')", [req.numero, req.tipo])
    return {"status": "ok"}

@app.post("/eliminar-habitacion/{numero}")
def eliminar_hab(numero: str):
    with get_db() as client:
        client.execute("DELETE FROM habitaciones WHERE numero=?", [numero])
    return {"status": "ok"}

@app.post("/ocupar-habitacion")
def ocupar(req: OcuparReq):
    fecha = req.fecha_ingreso if req.fecha_ingreso else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as client:
        rs = client.execute("INSERT INTO pacientes (nombre, edad, fecha_ingreso, medico) VALUES (?, ?, ?, ?)", [req.nombre_paciente.strip(), req.edad.strip(), fecha, req.medico.strip()])
        pid = rs.last_insert_rowid
        client.execute("UPDATE habitaciones SET estado='OCUPADA', paciente_id=? WHERE numero=?", [pid, req.numero_hab])
    return {"status": "ok"}

@app.post("/editar-paciente")
def editar_paciente(req: EditPacReq):
    with get_db() as client:
        client.execute("UPDATE pacientes SET nombre=?, edad=?, medico=?, fecha_ingreso=? WHERE id=?", 
                       [req.nombre.strip(), req.edad.strip(), req.medico.strip(), req.fecha_ingreso, req.id_paciente])
    return {"status": "ok"}
@app.post("/liberar-habitacion/{numero}")
def liberar(numero: str):
    with get_db() as client:
        rs = client.execute("SELECT paciente_id FROM habitaciones WHERE numero=?", [numero])
        if rs.rows and rs.rows[0][0]:
            fecha_egreso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            client.execute("UPDATE pacientes SET fecha_egreso=? WHERE id=?", [fecha_egreso, rs.rows[0][0]])
        client.execute("UPDATE habitaciones SET estado='LIBRE', paciente_id=NULL WHERE numero=?", [numero])
    return {"status": "ok"}

@app.get("/catalogo-medicamentos")
def catalogo_medicamentos():
    with get_db() as client:
        rs = client.execute("SELECT DISTINCT nombre_medicamento FROM consumos")
        return [f[0] for f in rs.rows]

@app.post("/agregar-medicamento")
def agregar_med(req: MedReq):
    pb_exacto = round(req.precio_base, 2)
    pf = round(pb_exacto * 1.40, 2)
    fh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with get_db() as client:
        rs = client.execute("SELECT id, cantidad, precio_base FROM consumos WHERE paciente_id=? AND nombre_medicamento=? AND presentacion=?", [req.paciente_id, req.nombre_med.strip(), req.presentacion.strip()])
        id_match = None
        cant_actual = 0
        for fila in rs.rows:
            if round(fila[2], 2) == pb_exacto:
                id_match = fila[0]
                cant_actual = fila[1]
                break
                
        if id_match:
            nueva_cantidad = cant_actual + req.cantidad
            nuevo_total = round(pf * nueva_cantidad, 2)
            client.execute("UPDATE consumos SET cantidad=?, precio_final=?, total_articulo=? WHERE id=?", [nueva_cantidad, pf, nuevo_total, id_match])
        else:
            tot = round(pf * req.cantidad, 2)
            client.execute("INSERT INTO consumos (paciente_id, nombre_medicamento, presentacion, cantidad, precio_base, precio_final, total_articulo, fecha_registro, registrado_por) VALUES (?,?,?,?,?,?,?,?,?)", 
                           [req.paciente_id, req.nombre_med.strip(), req.presentacion.strip(), req.cantidad, pb_exacto, pf, tot, fh, req.registrado_por])
    return {"status": "ok"}

@app.post("/editar-medicamento")
def editar_medicamento(req: EditReq):
    with get_db() as client:
        rs = client.execute("SELECT valor FROM configuracion WHERE clave='PIN_MAESTRO'")
        pin_guardado = str(rs.rows[0][0]).strip() if rs.rows else "1234"
        if str(req.pin_autorizacion).strip() != pin_guardado:
            raise HTTPException(status_code=401, detail="PIN inválido")
            
        pf = round(req.nuevo_precio * 1.40, 2)
        tot = round(pf * req.nueva_cantidad, 2)
        fh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        client.execute("UPDATE consumos SET cantidad=?, precio_base=?, precio_final=?, total_articulo=?, autorizado_por=?, fecha_modificacion=? WHERE id=?", [req.nueva_cantidad, req.nuevo_precio, pf, tot, "Administrador / Dir.", fh, req.id_consumo])
    return {"status": "ok"}

@app.post("/cambiar-pin")
def cambiar_pin(req: PinReq):
    with get_db() as client:
        client.execute("UPDATE configuracion SET valor=? WHERE clave='PIN_MAESTRO'", [str(req.nuevo_pin).strip()])
    return {"status": "ok"}

@app.get("/historial-paciente/{pid}")
def historial(pid: int):
    with get_db() as client:
        rs_pac = client.execute("SELECT nombre, edad, fecha_ingreso, medico FROM pacientes WHERE id = ?", [pid])
        pac = rs_pac.rows[0]
        rs_meds = client.execute("SELECT id, cantidad, nombre_medicamento, presentacion, precio_base, precio_final, total_articulo, fecha_registro, registrado_por, autorizado_por FROM consumos WHERE paciente_id = ?", [pid])
        lista = [{"id": r[0], "cant": r[1], "nom": r[2], "pres": r[3], "pb": r[4], "pf": r[5], "tot": r[6], "fec": r[7], "usr": r[8], "auth": r[9]} for r in rs_meds.rows]
    return {"paciente": {"nombre": pac[0], "edad": pac[1], "ingreso": pac[2], "medico": pac[3]}, "medicamentos": lista, "gran_total": sum(i["tot"] for i in lista)}

@app.get("/estadisticas")
def estadisticas():
    with get_db() as client:
        rs_habs = client.execute("SELECT COUNT(*) FROM habitaciones WHERE tipo IN ('Habitación', 'Suite')")
        total_habs = rs_habs.rows[0][0]
        
        año_actual = str(datetime.now().year)
        rs_pac = client.execute("SELECT id, nombre, edad, medico, fecha_ingreso, fecha_egreso FROM pacientes WHERE fecha_ingreso LIKE ? ORDER BY id DESC", [año_actual + "%"])
        pacientes_anuales = rs_pac.rows
        
    total_dias_estancia = 0
    lista_historial = []
    
    for p in pacientes_anuales:
        ingreso = p[4]
        egreso = p[5]
        try:
            t_ingreso = datetime.strptime(ingreso, "%Y-%m-%d %H:%M:%S")
            t_egreso = datetime.strptime(egreso, "%Y-%m-%d %H:%M:%S") if egreso else datetime.now()
            
            horas_totales = (t_egreso - t_ingreso).total_seconds() / 3600
            dias_completos = int(horas_totales // 24)
            horas_restantes = int(horas_totales % 24)
            
            dias_a_graficar = dias_completos
            if horas_restantes >= 6: 
                dias_a_graficar += 1
                
            total_dias_estancia += dias_a_graficar
            
            estado = "Alta" if egreso else "Internado"
            tiempo_str = f"{dias_completos} días, {horas_restantes} hrs"
            
            lista_historial.append({
                "nombre": p[1], "edad": p[2], "medico": p[3], "ingreso": ingreso.split(" ")[0],
                "tiempo": tiempo_str, "dias_fact": dias_a_graficar, "estado": estado
            })
        except: pass 
        
    dias_transcurridos_del_año = (datetime.now() - datetime(datetime.now().year, 1, 1)).days + 1
    capacidad_total_dias = total_habs * dias_transcurridos_del_año
    ocupacion_pct = round((total_dias_estancia / capacidad_total_dias) * 100, 1) if capacidad_total_dias > 0 else 0
    
    return {
        "total_habitaciones": total_habs, 
        "dias_consumidos": total_dias_estancia, 
        "porcentaje": ocupacion_pct, 
        "ingresos_anuales": len(pacientes_anuales), 
        "historial": lista_historial
    }

# --- RUTA MÁGICA PARA MIGRAR DATOS ---
@app.get("/migrar-nube")
def migrar_nube():
    if not os.path.exists(LOCAL_DB_PATH):
        return {"error": "No se encontró el archivo farmacia_hospital.db local."}
    try:
        local_conn = sqlite3.connect(LOCAL_DB_PATH)
        local_cursor = local_conn.cursor()
        
        with get_db() as client:
            local_cursor.execute("SELECT * FROM usuarios")
            for row in local_cursor.fetchall():
                client.execute("INSERT OR IGNORE INTO usuarios (usuario, password, rol) VALUES (?, ?, ?)", list(row))
                
            local_cursor.execute("SELECT * FROM pacientes")
            for row in local_cursor.fetchall():
                client.execute("INSERT OR IGNORE INTO pacientes (id, nombre, edad, fecha_ingreso, fecha_egreso, medico) VALUES (?, ?, ?, ?, ?, ?)", list(row))
                
            local_cursor.execute("SELECT * FROM habitaciones")
            for row in local_cursor.fetchall():
                client.execute("DELETE FROM habitaciones WHERE numero=?", [row[0]])
                client.execute("INSERT INTO habitaciones (numero, tipo, estado, paciente_id, color) VALUES (?, ?, ?, ?, ?)", list(row))
                
            local_cursor.execute("SELECT * FROM consumos")
            for row in local_cursor.fetchall():
                client.execute("INSERT OR IGNORE INTO consumos (id, paciente_id, nombre_medicamento, presentacion, cantidad, precio_base, precio_final, total_articulo, fecha_registro, registrado_por, autorizado_por, fecha_modificacion) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(row))
                
            local_cursor.execute("SELECT * FROM configuracion")
            for row in local_cursor.fetchall():
                client.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES (?, ?)", list(row))

        local_conn.close()
        return {"status": "ok", "mensaje": "Datos de tu PC migrados a la nube Turso con EXITO. Tus pacientes ya están a salvo."}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
