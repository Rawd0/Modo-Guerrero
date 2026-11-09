# Hoja de ruta

Mejoras previstas para próximas versiones, en el orden en que pensamos abordarlas.

## Hecho

- **0.2.0** Inicio de sesión propio (sin la contraseña de Umbrel), recordar dispositivo 90 días.
- **0.3.0** Tema (automático, claro, oscuro, negro) y color principal personalizables.
- **0.4.0** Varios usuarios en la misma instalación: panel de administración, datos, cuenta de
  Garmin y ajustes separados por usuario, sincronización por turnos.
- **0.5.0** Paquete de análisis (inspirado en Elevate, Runalyze e intervals.icu): progresión anual
  acumulada, ritmo ajustado a la pendiente (GAP), kilometraje de zapatillas, curva de ritmo, y
  monotonía y tensión semanal.
- **0.6.0** Copias de seguridad: automáticas a diario con retención, manuales, descarga y
  restauración segura (con copia previa automática). App en la pantalla de inicio (PWA básica).
- **0.6.1** Nuevo icono (G con pulso y laurel) y cabecera MODO / GUERRERO.
- **0.7.0** Objetivos de carrera: predicción según tu forma (VDOT de Daniels, Riegel y Garmin),
  proyección de la forma con afinamiento hasta el día, lista de preparación y resultado automático.
- **0.8.0** Plan de entrenamiento para cada objetivo: fases, volumen progresivo con descargas,
  sesiones con ritmos de Daniels, seguimiento automático de lo hecho y widget «Hoy toca».
- **0.8.1–0.8.2** Cabecera en iPhone, estado de la sincronización más claro, salud a 7 días.
- **0.9.0** Copia fuera del servidor (Nextcloud/WebDAV o Google Drive), comparar dos periodos,
  ritmo cumplido en las sesiones del plan e inicio con cuadrícula libre (calendario, sueño y rendimiento).

## Más adelante

- **HTTPS con Tailscale**, que desbloquea **Face ID con passkeys**, **notificaciones push** en el
  móvil (zapatillas, sesión de Garmin caducada, resumen semanal) y el modo sin conexión de la app.
- **Importar las zapatillas de Garmin Connect** (el «equipo» que ya tengas dado de alta allí) y su
  asignación a cada actividad.
- **Face ID con passkeys** (requiere HTTPS): iniciar sesión con Face ID / huella mediante WebAuthn,
  con la contraseña como respaldo.
- **Zonas e historial del atleta** (Elevate): FC máxima, de reposo y umbral con fecha, para que las
  carreras antiguas se analicen con los valores que tenías entonces.
- **Strava** como fuente complementaria (segmentos, kudos) o alternativa a Garmin. *(en curso, 0.10.0)*
- **Rutas repetidas** detectadas automáticamente y tu evolución en ellas (intervals.icu). *(en curso, 0.10.0)*
- **Preguntas en lenguaje natural** sobre tus datos usando un modelo local (Ollama).
- **Plan de entrenamiento, siguiente paso:** exportar las sesiones al reloj como entrenamientos de Garmin.
