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

## Más adelante

- **Importar las zapatillas de Garmin Connect** (el «equipo» que ya tengas dado de alta allí) y su
  asignación a cada actividad.
- **Face ID con passkeys**: iniciar sesión con Face ID / huella mediante WebAuthn. Requiere entrar
  por HTTPS con un nombre de dominio (certificados HTTPS de Tailscale:
  `https://<servidor>.<red>.ts.net`). La contraseña quedaría como respaldo.
- **Zonas e historial del atleta** (Elevate): FC máxima, de reposo y umbral con fecha, para que las
  carreras antiguas se analicen con los valores que tenías entonces.
- **Predicción de carrera según tu forma** (Runalyze), comparada con la de Garmin.
- **Botón «No me llega el código»** en la verificación en dos pasos de Garmin: mostrar por dónde dice
  Garmin que ha enviado el código y reintentar por el método web, que pide explícitamente el envío.
- **Strava** como fuente complementaria (segmentos, kudos) o alternativa a Garmin.
- **Inicio con cuadrícula libre:** widgets redimensionables y nuevos widgets (objetivos, calendario
  del mes, sueño frente a rendimiento).
- **Comparar dos periodos** lado a lado (intervals.icu).
- **Rutas repetidas** detectadas automáticamente y tu evolución en ellas (intervals.icu).
- **Preguntas en lenguaje natural** sobre tus datos usando un modelo local (Ollama).
- **Objetivos y preparación de carreras:** fecha de la carrera, plan y seguimiento.
