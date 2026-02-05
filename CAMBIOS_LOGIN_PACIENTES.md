# 🔄 Actualización: Login Multiempresa para Pacientes

## 📋 Resumen de cambios

Se ha implementado un sistema de login para pacientes donde **cada empresa tiene su propia URL** y el mismo teléfono puede ser un paciente diferente en cada empresa.

---

## 🗂️ Cambios en archivos

### 1. **routes/paciente.py** ✅
- ❌ Eliminado: `@app.route("/auth/login_paciente")`
- ✅ Agregado: `@paciente_bp.route("/empresa/<int:idEmpresa>/auth/login", methods=["POST"])`
  - Valida que el teléfono existe en la empresa específica
  - Envía código por SMS/WhatsApp
  - Guarda `idEmpresa_temp` en sesión

- ❌ Eliminado: `@app.route("/validar_codigo")`
- ✅ Agregado: `@paciente_bp.route("/validar_codigo_empresa", methods=["POST"])`
  - Valida código
  - Verifica que el paciente existe en esa empresa
  - Inicia sesión con `idEmpresa`

- ✅ Modificado: `@paciente_bp.route("/alta")` → `@paciente_bp.route("/empresa/<int:idEmpresa>/alta")`
  - Ahora registra el paciente en la empresa específica
  - Valida que no existe duplicado en esa empresa
  - Inserta `idEmpresa` en la tabla

### 2. **templates/login_paciente.html** ✅
- Actualizado JavaScript para:
  - Extraer `idEmpresa` de la URL
  - Pasar `idEmpresa` en todas las llamadas AJAX
  - Redirigir a `/empresa/{idEmpresa}/paciente/alta` si no existe
  - Redirigir a `/empresa/{idEmpresa}/paciente/menu` al validar

### 3. **routes/citas_paciente.py** ✅
- ✅ Agregado: `@citas_paciente_bp.route("/empresa/<int:idEmpresa>/paciente/menu")`
  - Nueva ruta que incluye empresa en la URL
  - Valida que la sesión coincida con la empresa de la URL

- 🔄 Modificado: `@citas_paciente_bp.route("/paciente/menu")`
  - Ahora redirige a la nueva ruta con empresa

### 4. **app.py** ✅
- Agregado comentario aclaratorio en la ruta `/empresa/<int:idEmpresa>/paciente/login`
- Mantiene la estructura actual, solo agrega documentación

---

## 🗄️ Cambios en Base de Datos

### Migración requerida:
```sql
ALTER TABLE paciente
ADD COLUMN idEmpresa INT DEFAULT 1 NOT NULL,
ADD CONSTRAINT fk_paciente_empresa 
    FOREIGN KEY (idEmpresa) REFERENCES Empresa(idEmpresa) ON DELETE CASCADE;

CREATE UNIQUE INDEX idx_paciente_telefono_empresa 
ON paciente(telefono, idEmpresa);
```

**Archivo:** `MIGRACION_PACIENTE_EMPRESA.sql`

---

## 🔗 Nuevas rutas

### Para pacientes:

| Acción | Ruta Anterior | Ruta Nueva | Método |
|--------|---------------|-----------|--------|
| Ver login | `/login/paciente` | `/empresa/{id}/paciente/login` | GET |
| Enviar código | `POST /paciente/auth/login_paciente` | `POST /paciente/empresa/{id}/auth/login` | POST |
| Validar código | `POST /paciente/validar_codigo` | `POST /paciente/validar_codigo_empresa` | POST |
| Registrarse | `/paciente/alta` | `/empresa/{id}/paciente/alta` | GET/POST |
| Menú paciente | `/paciente/menu` | `/empresa/{id}/paciente/menu` | GET |

---

## 🚀 Flujo de login actual

```
1. Usuario accede a: /empresa/1/paciente/login
2. Ve formulario de login (sin elegir empresa)
3. Ingresa teléfono
4. Sistema verifica que existe en empresa 1
5. Envía código por SMS/WhatsApp
6. Usuario valida código
7. Sistema inicia sesión con:
   - idPaciente
   - NombrePaciente
   - idEmpresa
8. Redirige a: /empresa/1/paciente/menu
```

---

## ⚠️ Pasos a ejecutar

### 1. **Ejecutar migración SQL**
```bash
# Conectar a MySQL
mysql -u usuario -p base_datos < MIGRACION_PACIENTE_EMPRESA.sql
```

### 2. **Verificar que la tabla tiene la columna**
```sql
SELECT * FROM information_schema.COLUMNS 
WHERE TABLE_NAME='paciente' AND COLUMN_NAME='idEmpresa';
```

### 3. **Actualizar variables de entorno (si es necesario)**
- Las rutas ahora requieren que `idEmpresa` esté en la URL
- No hay cambios en `.env`

### 4. **Testear el flujo**
- Ir a `/empresa/1/paciente/login` (ajusta ID según tu BD)
- Verificar que el login funciona
- Probar con mismo teléfono en diferentes empresas

---

## 🎯 Ventajas del nuevo sistema

✅ **Multiempresa nativo:** Mismo teléfono en múltiples empresas  
✅ **URLs limpias:** Cada empresa tiene su propia ruta  
✅ **Validación por empresa:** No puede loguear con teléfono de otra empresa  
✅ **Escalable:** Fácil agregar más empresas  
✅ **Seguro:** Validación en cada paso  

---

## 🔮 Próximos pasos

Cuando separes "sanacionAlternativa" de la app de citas:
- Crea una URL específica para "sanacionAlternativa" (ej: `sanacionAlternativa.com/citas`)
- Cada empresa tendrá: `miempresa.com/empresa/1/paciente/login`
- La app de citas será completamente multiempresa

---

## 📝 Notas importantes

- La columna `idEmpresa` en la tabla `paciente` es **REQUERIDA**
- El índice único `(telefono, idEmpresa)` permite el mismo teléfono en diferentes empresas
- Las sesiones ahora guardan `idEmpresa` para validaciones futuras
- Las rutas antiguas se mantienen con redirects para compatibilidad

