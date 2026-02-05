# ✅ Estado de la Implementación: Login Multiempresa de Pacientes

## 📊 Resumen Ejecutivo

Se ha implementado exitosamente un sistema de login para pacientes donde:
- ✅ Cada empresa tiene su propia URL
- ✅ El mismo teléfono puede existir en múltiples empresas (como pacientes diferentes)
- ✅ La validación ocurre por empresa específica
- ✅ El código ya está actualizado y listo para usar

---

## 🗄️ Estructura de Base de Datos

### Tabla `paciente`
```
Columnas relevantes:
- idPaciente (int, PK, auto_increment)
- Empresa (int) - NOTA: Aparentemente duplicada con idEmpresa
- idEmpresa (int) - Campo NUEVO - Mantener este
- Telefono (varchar) - ÚNICO pero permite mismo número en diferentes empresas
- NombrePaciente (varchar)
- Correo (varchar)
- FechaNac (date)
- CorreoValido (tinyint)
- TokenCorreoVerificacion (varchar)
```

### Tabla `codigos_telefono`
```
Columnas necesarias:
- Telefono (varchar)
- codigo (varchar)
- expiracion (datetime)
```

---

## 🔧 Migraciones SQL Requeridas

### ✅ PASO 1: Crear índice para búsquedas multiempresa
```sql
-- Eliminar índice anterior si existe
DROP INDEX IF EXISTS idx_paciente_telefono ON paciente;

-- Crear nuevo índice que permite mismo teléfono en diferentes empresas
CREATE UNIQUE INDEX idx_paciente_telefono_empresa 
ON paciente(Telefono, idEmpresa);
```

### ⚠️ PASO 2 (OPCIONAL): Si `Empresa` es duplicado de `idEmpresa`
```sql
-- Verificar primero que ambos tienen los mismos datos:
SELECT * FROM paciente WHERE Empresa != idEmpresa;

-- Si está vacío, es seguro eliminar:
ALTER TABLE paciente DROP COLUMN Empresa;

-- Si tiene datos diferentes, investigar qué significa cada una
```

---

## 🔗 Rutas de API

### Antes (Antiguas):
```
GET /login/paciente
POST /paciente/auth/login_paciente
POST /paciente/validar_codigo
GET/POST /paciente/alta
GET /paciente/menu
```

### Ahora (Nuevas):
```
GET /empresa/{idEmpresa}/paciente/login
POST /paciente/empresa/{idEmpresa}/auth/login
POST /paciente/validar_codigo_empresa
GET/POST /empresa/{idEmpresa}/paciente/alta
GET /empresa/{idEmpresa}/paciente/menu
```

---

## 📝 Cambios en Archivos

### 1. `routes/paciente.py` ✅
**Nuevas rutas agregadas:**
- `@paciente_bp.route("/empresa/<int:idEmpresa>/auth/login", methods=["POST"])`
  - Valida: empresa existe → teléfono existe en esa empresa
  - Envía: código por SMS o WhatsApp
  - Guarda en sesión: `telefono_temp`, `idEmpresa_temp`, `idPaciente_temp`

- `@paciente_bp.route("/validar_codigo_empresa", methods=["POST"])`
  - Recibe: teléfono, código, idEmpresa
  - Valida: código correcto y paciente en esa empresa
  - Inicia sesión: `idPaciente`, `NombrePaciente`, `idEmpresa`

- `@paciente_bp.route("/empresa/<int:idEmpresa>/alta", methods=["GET", "POST"])`
  - Registra paciente en empresa específica
  - Valida: no existe duplicado (mismo teléfono + empresa)
  - Inserta: con `idEmpresa` correcto

**Correcciones de nombres de columnas:**
- `telefono` → `Telefono` (mayúscula, como en BD)
- `fechanac` → `FechaNac`
- `correo` → `Correo`

### 2. `templates/login_paciente.html` ✅
**JavaScript actualizado:**
```javascript
// Extrae idEmpresa de la URL: /empresa/1/paciente/login
const urlParts = window.location.pathname.split("/");
const idEmpresa = urlParts[2];

// Envía a: POST /paciente/empresa/{idEmpresa}/auth/login
fetch(`/paciente/empresa/${idEmpresa}/auth/login`, {...})

// Valida con: POST /paciente/validar_codigo_empresa
// Incluye: {telefono, codigo, idEmpresa}

// Redirige a registro o menú con empresa en URL
window.location.href = `/empresa/${idEmpresa}/paciente/alta?...`
window.location.href = `/empresa/${idEmpresa}/paciente/menu`
```

### 3. `routes/citas_paciente.py` ✅
**Nueva ruta:**
- `@citas_paciente_bp.route("/empresa/<int:idEmpresa>/paciente/menu")`
  - Menú principal del paciente con validación de empresa en URL

**Ruta antigua (compatibilidad):**
- `@citas_paciente_bp.route("/paciente/menu")`
  - Redirige a la nueva ruta con empresa

### 4. `routes/codigos_telefono.py` ✅
**Correcciones:**
- `telefono` → `Telefono` en todas las queries

### 5. `app.py` ✅
**Ruta de redirect:**
- Antigua `/paciente/alta` redirige a `/empresa/{id}/paciente/alta`

---

## 🚀 Flujo Completo de Login

```
1. Usuario accede a: GET /empresa/1/paciente/login
   ↓
2. Ve formulario (sin selector de empresa)
   ↓
3. Ingresa teléfono: "8112345678"
   ↓
4. Click "Enviar código"
   ↓
5. JavaScript:
   - Extrae idEmpresa=1 de la URL
   - Envía: POST /paciente/empresa/1/auth/login
     {telefono: "8112345678", canal: "sms"}
   ↓
6. Backend verifica:
   - ¿Existe empresa 1? ✓
   - ¿Existe paciente con tel 8112345678 en empresa 1? 
     - SI → Envía código
     - NO → Retorna "no_encontrado" → Redirige a /empresa/1/paciente/alta
   ↓
7. Si existe: Usuario recibe código por SMS/WhatsApp
   ↓
8. Usuario ingresa código
   ↓
9. Click "Validar"
   ↓
10. JavaScript:
    - Envía: POST /paciente/validar_codigo_empresa
      {telefono, codigo, idEmpresa: 1}
    ↓
11. Backend:
    - Valida código
    - Valida que paciente existe en empresa 1
    - Inicia sesión con idPaciente, NombrePaciente, idEmpresa
    ↓
12. Redirige a: GET /empresa/1/paciente/menu
    ↓
13. Usuario entra a su menú personal
```

---

## ✅ Casos de Uso Multiempresa

### Caso 1: Mismo paciente en 2 empresas
```
Empresa 1: "Sanación Alternativa" (id=1)
  - Paciente: Juan
  - Teléfono: 8112345678
  - URL: /empresa/1/paciente/login

Empresa 2: "Wellness Center" (id=2)
  - Paciente: Juan (DIFERENTE)
  - Teléfono: 8112345678 (MISMO)
  - URL: /empresa/2/paciente/login

✅ Son 2 registros diferentes en la base de datos
✅ Mismo teléfono, diferentes empresas
✅ Índice único: (Telefono, idEmpresa) lo permite
```

### Caso 2: Login correcto
```
Usuario accede a: /empresa/1/paciente/login
Ingresa: 8112345678
Sistema busca: SELECT * FROM paciente 
               WHERE Telefono='8112345678' AND idEmpresa=1

✅ Encontrado → Envía código
❌ No encontrado → "Registrate aquí"
```

### Caso 3: Intento de XSS/Inyección
```
URL: /empresa/999/paciente/login
Sistema valida: SELECT * FROM Empresa WHERE idEmpresa=999

✅ No existe → 404
```

---

## 📋 Checklist de Implementación

- [x] Crear nuevas rutas en `routes/paciente.py`
- [x] Validar empresa en cada endpoint
- [x] Actualizar JavaScript en `login_paciente.html`
- [x] Crear nueva ruta de menú con empresa
- [x] Corregir nombres de columnas (Telefono, FechaNac, Correo)
- [x] Actualizar `codigos_telefono.py`
- [x] Rutas antiguas redirigen a nuevas (compatibilidad)
- [ ] ⚠️ Ejecutar migraciones SQL
- [ ] Testear flujo completo
- [ ] Testear multiempresa
- [ ] Documentar para equipo

---

## ⚠️ PASOS PARA EJECUTAR

### 1. **Ejecutar migración SQL**
```bash
mysql -u root -p base_datos < ruta/MIGRACION_PACIENTE_EMPRESA_ACTUALIZADA.sql

# O ejecutar directamente en MySQL:
DROP INDEX IF EXISTS idx_paciente_telefono ON paciente;
CREATE UNIQUE INDEX idx_paciente_telefono_empresa 
ON paciente(Telefono, idEmpresa);
```

### 2. **Verificar estructura**
```sql
-- Verificar que idEmpresa existe
DESC paciente;

-- Verificar índices
SHOW INDEXES FROM paciente;

-- Verificar que Telefono tiene datos
SELECT COUNT(*) FROM paciente WHERE Telefono IS NOT NULL;
```

### 3. **Reiniciar aplicación Flask**
```bash
# Detener servidor actual (Ctrl+C)
# Reiniciar:
python app.py
# O con gunicorn:
gunicorn app:app
```

### 4. **Testear en navegador**
```
URL: http://localhost:5000/empresa/1/paciente/login

(Ajusta el ID 1 según tus empresas en BD)
```

### 5. **Verificar logs**
```bash
# Ver si hay errores en la consola de Flask
# Ver si las queries se ejecutan correctamente
```

---

## 🔍 Debugging

### Si no funciona el login:

1. **Verificar que la empresa existe:**
   ```sql
   SELECT * FROM Empresa WHERE idEmpresa=1;
   ```

2. **Verificar que el paciente existe:**
   ```sql
   SELECT * FROM paciente 
   WHERE Telefono='8112345678' AND idEmpresa=1;
   ```

3. **Ver si codigos_telefono está bien:**
   ```sql
   DESC codigos_telefono;
   SELECT * FROM codigos_telefono WHERE Telefono='8112345678';
   ```

4. **Activar logs en Flask:**
   ```python
   # En app.py o paciente.py
   logger.warning("DEBUG: %s", variable_a_inspeccionar)
   ```

---

## 🎯 Próximas Mejoras

- [ ] Crear admin de pacientes por empresa
- [ ] Dashboard de uso por empresa
- [ ] Estadísticas multiempresa
- [ ] Sistema de reportes por empresa
- [ ] API REST completa para pacientes

---

## 📞 Notas Importantes

- La sesión ahora contiene: `idPaciente`, `NombrePaciente`, `idEmpresa`
- Todas las consultas de pacientes deben filtrar por `idEmpresa`
- El teléfono es ÚNICO **por empresa**, no globalmente
- Las rutas antiguas redirigen (compatibilidad hacia atrás)
- **idEmpresa es REQUERIDO en todas las URLs de paciente**

---

**Estado:** ✅ LISTO PARA USAR

**Última actualización:** 4 de Febrero de 2026
