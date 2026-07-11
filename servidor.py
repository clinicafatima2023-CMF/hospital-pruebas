from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import List, Optional
import libsql_client
import os
from datetime import datetime
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

url = os.getenv("TURSO_URL")
token = os.getenv("TURSO_TOKEN")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_db(): return libsql_client.create_client(url=url, auth_token=token)

def init_db():
    db = get_db()
    # Tabla de Usuarios Reales
    db.execute("CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, rol TEXT)")
    
    # Crear usuario admin por defecto si no existe
    res = db.execute("SELECT * FROM usuarios WHERE username = 'admin'")
    if not res.rows:
        hash_pw = pwd_context.hash("1234")
        db.execute(f"INSERT INTO usuarios (username, password, rol) VALUES ('admin', '{hash_pw}', 'administrador')")

    # Tablas existentes
    db.execute("CREATE TABLE IF NOT EXISTS pin_maestro (id INTEGER PRIMARY KEY, pin TEXT)")
    res_pin = db.execute("SELECT * FROM pin_maestro")
    if not res_pin.rows: db.execute("INSERT INTO pin_maestro (pin) VALUES ('1234')")

    db.execute("CREATE TABLE IF NOT EXISTS pacientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, edad TEXT, medico TEXT, habitacion TEXT, fecha_ingreso TEXT, estado TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS consumos (id INTEGER PRIMARY KEY AUTOINCREMENT, paciente_id INTEGER, nombre_med TEXT, presentacion TEXT, cantidad REAL, precio_base REAL, registrado_por TEXT, fecha TEXT, autorizado_por TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS catalogo_meds (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE)")
    db.execute("CREATE TABLE IF NOT EXISTS habitaciones (numero TEXT PRIMARY KEY, tipo TEXT)")
    
    # NUEVA TABLA: FOLIOS
    db.execute("CREATE TABLE IF NOT EXISTS folios (id INTEGER PRIMARY KEY AUTOINCREMENT, paciente_id INTEGER, habitacion TEXT, total REAL, estado TEXT, emitido_por TEXT, fecha TEXT, cancelado_por TEXT)")
    
    # Habitaciones por defecto
    res_habs = db.execute("SELECT * FROM habitaciones")
    if not res_habs.rows:
        habs = [('1','Habitación'),('2','Habitación'),('3','Habitación'),('4','Habitación'),('5','Habitación'),('6','Habitación'),('7','Suite'),('8','Suite'),('Urgencias 1','Urgencias'),('Urgencias 2','Urgencias'),('Incubadora 1','Incubadora'),('Consultorio 1','Consultorio')]
        for h in habs: db.execute(f"INSERT INTO habitaciones (numero, tipo) VALUES ('{h[0]}', '{h[1]}')")
    db.close()

init_db()

class LoginData(BaseModel): usuario: str; password: str
class NuevoUsuario(BaseModel): username: str; password: str; rol: str; pin_autorizacion: str

@app.post("/login")
def login(data: LoginData):
    db = get_db()
    res = db.execute(f"SELECT password, rol FROM usuarios WHERE username = '{data.usuario}'")
    db.close()
    if res.rows and pwd_context.verify(data.password, res.rows[0][0]):
        return {"usuario": data.usuario, "rol": res.rows[0][1]}
    raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

@app.post("/crear-usuario")
def crear_usuario(data: NuevoUsuario):
    db = get_db()
    pin_real = db.execute("SELECT pin FROM pin_maestro WHERE id = 1").rows[0][0]
    if data.pin_autorizacion != pin_real:
        db.close()
        raise HTTPException(status_code=403, detail="PIN incorrecto")
    hash_pw = pwd_context.hash(data.password)
    try:
        db.execute(f"INSERT INTO usuarios (username, password, rol) VALUES ('{data.username}', '{hash_pw}', '{data.rol}')")
        db.close()
        return {"status": "ok"}
    except Exception as e:
        db.close()
        raise HTTPException(status_code=400, detail="El usuario ya existe")

class PacienteAlta(BaseModel): numero_hab: str; nombre_paciente: str; edad: str; medico: str; fecha_ingreso: Optional[str] = None
class ConsumoNuevo(BaseModel): paciente_id: int; nombre_med: str; presentacion: str; cantidad: float; precio_base: float; registrado_por: str

@app.get("/habitaciones")
def obtener_habitaciones():
    db = get_db()
    habs = db.execute("SELECT numero, tipo FROM habitaciones").rows
    pacientes_activos = db.execute("SELECT id, habitacion, nombre, medico, fecha_ingreso, edad FROM pacientes WHERE estado = 'Internado'").rows
    db.close()
    
    dict_pacientes = {p[1]: p for p in pacientes_activos}
    resultado = []
    for h in habs:
        num = h[0]; tipo = h[1]
        if num in dict_pacientes:
            p = dict_pacientes[num]
            resultado.append({"numero": num, "tipo": tipo, "estado": "OCUPADA", "paciente_id": p[0], "nombre": p[2], "medico": p[3], "fecha_ingreso": p[4], "edad": p[5]})
        else:
            resultado.append({"numero": num, "tipo": tipo, "estado": "LIBRE"})
    return resultado

@app.post("/ocupar-habitacion")
def ocupar_habitacion(data: PacienteAlta):
    db = get_db()
    fecha = data.fecha_ingreso if data.fecha_ingreso else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(f"INSERT INTO pacientes (nombre, edad, medico, habitacion, fecha_ingreso, estado) VALUES ('{data.nombre_paciente}', '{data.edad}', '{data.medico}', '{data.numero_hab}', '{fecha}', 'Internado')")
    db.close()
    return {"status": "ok"}

@app.get("/historial-paciente/{paciente_id}")
def obtener_historial_paciente(paciente_id: int):
    db = get_db()
    p = db.execute(f"SELECT nombre, habitacion, fecha_ingreso, edad, medico FROM pacientes WHERE id = {paciente_id}").rows[0]
    meds = db.execute(f"SELECT id, nombre_med, presentacion, cantidad, precio_base, registrado_por, autorizado_por FROM consumos WHERE paciente_id = {paciente_id}").rows
    
    # Buscar folios activos de este paciente
    folios = db.execute(f"SELECT id, estado, total, emitido_por FROM folios WHERE paciente_id = {paciente_id} ORDER BY id DESC").rows
    db.close()

    historial_meds = []
    gran_total = 0
    for m in meds:
        precio_final = m[4] * 1.40
        subtotal = m[3] * precio_final
        gran_total += subtotal
        historial_meds.append({"id": m[0], "nom": m[1], "pres": m[2], "cant": m[3], "pb": round(m[4],2), "pf": round(precio_final,2), "tot": round(subtotal,2), "usr": m[5], "auth": m[6]})
    
    folio_activo = None
    if folios and folios[0][1] == 'ACTIVO':
        folio_activo = {"id": folios[0][0], "total": folios[0][2], "emitido_por": folios[0][3]}

    return {
        "paciente": {"nombre": p[0], "habitacion": p[1], "ingreso": p[2], "edad": p[3], "medico": p[4]},
        "medicamentos": historial_meds,
        "gran_total": round(gran_total, 2),
        "folio_activo": folio_activo
    }

@app.post("/agregar-medicamento")
def agregar_medicamento(data: ConsumoNuevo):
    db = get_db()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(f"INSERT INTO consumos (paciente_id, nombre_med, presentacion, cantidad, precio_base, registrado_por, fecha) VALUES ({data.paciente_id}, '{data.nombre_med}', '{data.presentacion}', {data.cantidad}, {data.precio_base}, '{data.registrado_por}', '{fecha}')")
    try: db.execute(f"INSERT INTO catalogo_meds (nombre) VALUES ('{data.nombre_med}')")
    except: pass
    db.close()
    return {"status": "ok"}

# --- NUEVOS ENDPOINTS PARA FOLIOS ---
class GenerarFolioData(BaseModel): paciente_id: int; habitacion: str; total: float; usuario: str
class CancelarFolioData(BaseModel): folio_id: int; usuario: str; pin_autorizacion: str

@app.post("/generar-folio")
def generar_folio(data: GenerarFolioData):
    db = get_db()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(f"INSERT INTO folios (paciente_id, habitacion, total, estado, emitido_por, fecha) VALUES ({data.paciente_id}, '{data.habitacion}', {data.total}, 'ACTIVO', '{data.usuario}', '{fecha}')")
    # Obtener el ID insertado
    res = db.execute("SELECT seq FROM sqlite_sequence WHERE name='folios'")
    folio_id = res.rows[0][0]
    db.close()
    return {"status": "ok", "folio_id": folio_id}

@app.post("/cancelar-folio")
def cancelar_folio(data: CancelarFolioData):
    db = get_db()
    pin_real = db.execute("SELECT pin FROM pin_maestro WHERE id = 1").rows[0][0]
    if data.pin_autorizacion != pin_real:
        db.close()
        raise HTTPException(status_code=403, detail="PIN incorrecto")
    
    db.execute(f"UPDATE folios SET estado = 'CANCELADO', cancelado_por = '{data.usuario}' WHERE id = {data.folio_id}")
    db.close()
    return {"status": "ok"}

@app.post("/liberar-habitacion/{numero}")
def liberar_habitacion(numero: str):
    db = get_db()
    db.execute(f"UPDATE pacientes SET estado = 'Alta' WHERE habitacion = '{numero}' AND estado = 'Internado'")
    db.close()
    return {"status": "ok"}

@app.get("/estadisticas")
def estadisticas(): return {"porcentaje": 0, "dias_consumidos": 0, "ingresos_anuales": 0, "historial": []}

@app.get("/catalogo-medicamentos")
def catalogo():
    db = get_db()
    res = db.execute("SELECT nombre FROM catalogo_meds ORDER BY nombre ASC").rows
    db.close()
    return [r[0] for r in res]

@app.get("/logo")
def get_logo(): return FileResponse("logo fatima.jpg")
@app.get("/")
def get_index(): return FileResponse("index.html")
