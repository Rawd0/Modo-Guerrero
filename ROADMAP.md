# Hoja de ruta

Mejoras previstas para próximas versiones, en el orden en que pensamos abordarlas.

## Hecho

- **0.2.0** Inicio de sesión propio (sin la contraseña de Umbrel), recordar dispositivo 90 días.
- **0.3.0** Tema (automático, claro, oscuro, negro) y color principal personalizables.
- **0.4.0** Varios usuarios en la misma instalación: panel de administración, datos, cuenta de
  Garmin y ajustes separados por usuario, sincronización por turnos.

## Próximo paquete: análisis de carrera

Inspirado en Elevate, Runalyze e intervals.icu.

- **Progresión anual acumulada** (Elevate): kilómetros acumulados de cada año superpuestos día a
  día, para ver si vas por delante o por detrás de otros años. También para tiempo y desnivel.
- **Ritmo ajustado a la pendiente (GAP)** (Elevate): ritmo equivalente en llano para cada carrera,
  gráfica y parcial, de modo que una tirada con cuestas se pueda comparar con una llana.
- **Kilometraje de zapatillas** (Runalyze, intervals.icu): dar de alta cada par, asignarlo a las
  carreras (con un par por defecto) y avisar cuando se acerca al límite de km.
- **Curva de ritmo** (intervals.icu): tu mejor ritmo sostenido para cada duración (1 min a 3 h),
  histórica y de los últimos 90 días, para ver en qué rangos has mejorado.
- **Monotonía y tensión semanal** (Runalyze): monotonía = carga media diaria / desviación típica de
  la carga de la semana; tensión = carga semanal × monotonía. Aviso cuando la tensión es alta o el
  entrenamiento es demasiado uniforme, junto a la forma (TSB) en la página de Forma y como widget.

## Más adelante

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
