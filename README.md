# WSC Simulation Challenge 2026 - Simulación Marítima (Python)

Este repositorio contiene la base de código en Python para participar en el **WSC Simulation Challenge 2026**. El programa modela una red de transporte marítimo global de contenedores (TEUs), simulando el tránsito de barcos, reservas de carga, operaciones portuarias y congestión bajo diferentes escenarios (incluyendo eventos de disrupción).

El simulador está construido sobre **O2DESPy**, una biblioteca en Python para Simulación de Eventos Discretos Orientada a Objetos (Object-Oriented Discrete-Event Simulation).

---

## Estructura del Proyecto

* **`main.py`**: Punto de entrada principal. Ejecuta la simulación, imprime estadísticas en tiempo real, guarda reportes y levanta el servidor web del dashboard.
* **`config/`**: Configuración central del simulador (`simulation_config.py`), incluyendo días de simulación, período de calentamiento (*warm-up*) y multiplicadores de congestión.
* **`scenario_builders/`**: Constructores de escenarios. Permite alternar entre el escenario base estable (`baseline_stable_scenario.py`) y escenarios con disrupción (`disruption_scenario.py`).
* **`response_strategies/`**: Aquí es donde los participantes implementan sus estrategias de decisión.
  * `user_strategy.py`: Punto de entrada de la estrategia personalizada.
  * `round2_strategy.py`: Implementación de la estrategia vigente para Round 2.
  * `optimize_round2.py`: Búsqueda persistente de parámetros mediante Optuna.
  * `default_strategy.py`: Estrategia por defecto que sirve como *fallback* si tu estrategia no toma una decisión.
* **`simulation_model/`**: El núcleo de la lógica y clases del modelo de simulación.
* **`maritime_data_context/`**: Clases y estructuras de datos que representan el contexto del negocio marítimo (barcos, puertos, rutas, reservas, etc.).
* **`dashboard/`**: Aplicación web frontend (HTML/CSS/JS) y servidor ligero de desarrollo (`serve_gui.py`) para visualizar interactivamente las estadísticas de salida.
* **`Input/`**: Archivos CSV con los datos de entrada (puertos, rutas de servicio, matriz de demanda, etc.).
* **`Output/`**: Directorio donde se escriben los resultados en formato CSV (KPIs, utilización de rutas, tiempos de transporte).
* **`Logs/`**: Directorio donde se almacenan las bitácoras detalladas del progreso de cada ejecución.
* **`o2despy/`**: Subproyecto local con la librería base de simulación O2DES en Python.

---

## Requisitos Previos

* Python **>= 3.8** (o compatible con las librerías indicadas).
* Entorno de terminal (Linux/macOS o Windows con soporte Bash/PowerShell).

---

## Instalación y Configuración

Se recomienda el uso de un entorno virtual de Python (`venv`) para evitar conflictos de dependencias.

1. **Clonar el repositorio** e ingresar al directorio del proyecto:

    ```bash
    git clone https://github.com/alemanuel18/SimulationChallenge2026_Py_Round2.git
    ```

    ```bash
    cd SimulationChallenge2026_Py_Round2
    ```

2. **Crear y activar un entorno virtual**:
    * **En Linux/macOS:**

        ```bash
        python -m venv .venv
        source .venv/bin/activate
        ```

    * **En Windows (PowerShell):**

        ```powershell
        python -m venv .venv
        source .venv\Scripts\Activate.ps1
        source .venv/Scripts/activate
        ```
    * **Desactivar el entorno virtual:**
        Para salir/desactivar el entorno virtual en cualquier sistema, ejecuta:
        ```bash
        deactivate
        ```

3. **Instalar dependencias**:
    El archivo `requirements.txt` incluye la instalación en modo editable de la librería local `o2despy` (`-e ./o2despy`), además de dependencias como `pandas`, `numpy`, `loguru` y `pytest`:

    ```bash
    pip install -r requirements.txt
    python -m pip install -r requirements.txt
    ```

---

## Cómo Ejecutar el Programa

### 1. Correr la Simulación

Para iniciar la simulación completa, ejecuta:

```bash
python main.py
```

Al hacerlo:

* Se cargará el escenario configurado (por defecto, el escenario con disrupción).
* Se realizará la fase de calentamiento (*warm-up* de 140 días por defecto) para llevar la red a un estado inicial realista.
* Se ejecutará la simulación de medición (360 días por defecto), mostrando estadísticas consolidadas en consola cada cierto intervalo.
* Al finalizar, escribirá los archivos de resultados en la carpeta `Output/` y guardará la bitácora de eventos en `Logs/`.
* Finalmente, **iniciará de manera automática el servidor web del dashboard** y abrirá tu navegador predeterminado en `http://127.0.0.1:8000/dashboard/`.

### 2. Levantar el Dashboard de Forma Manual

Si deseas abrir el visualizador sin volver a correr la simulación (utilizando los últimos archivos guardados en `Output/`):

```bash
python dashboard/serve_gui.py
```

Abre tu navegador en: [http://127.0.0.1:8000/dashboard/](http://127.0.0.1:8000/dashboard/)

---

## Personalización de Estrategias (Desafío)

El objetivo del desafío es mejorar la eficiencia de la red (por ejemplo,
reducir el Average Transport Time de la carga) ante las disrupciones. Toda la
implementación personalizada de este proyecto debe mantenerse dentro de
**`response_strategies/`**. `user_strategy.py` funciona como punto de entrada y
la estrategia vigente está separada en `round2_strategy.py`.

Ahí puedes implementar tu propia lógica para:

* `select_vessel_for_berth`: Decidir qué barco entra al muelle primero en puertos congestionados.
* `create_alternative_service_routes`: Crear rutas alternativas aprovechando los barcos y tramos existentes.
* `assign_associated_bookings`: Definir la cadena de reservas inicial para un contenedor.
* `adjust_bookings_before_cargo_handling`: Re-planificar reservas de cargamento en tránsito cuando ocurre una disrupción.

La estrategia de usuario ya se encuentra habilitada para las ejecuciones de
Round 2; no es necesario modificar archivos fuera de `response_strategies/`.

---

## Estrategia actual de Round 2

La estrategia activa se encuentra en `response_strategies/round2_strategy.py` y
es utilizada desde `response_strategies/user_strategy.py`. Está limitada al
escenario publicado de Round 2: si no reconoce exactamente sus rutas y
disrupciones, permite que la estrategia por defecto actúe como *fallback*.

El resultado validado actualmente es:

* `Loss` original: **34.574028**.
* `Loss` de la estrategia actual: **3.295500**.
* Reducción obtenida: aproximadamente **90.5 %**.

La estrategia combina cuatro mecanismos:

1. **Enrutamiento por tiempo esperado.** No utiliza solamente distancia. Tiene
   en cuenta frecuencia del servicio, espera estimada para embarcar,
   transbordos, tiempo de navegación, escalas, cierres portuarios y
   multiplicadores activos o futuros.
2. **Desvío preventivo de flota completa.** Antes de la disrupción del tramo
   Colombo–New Jersey (`S5`), mueve la flota afectada a un ciclo alternativo
   válido. Cuando termina el evento, restaura la ruta original y sus reservas.
   Optuna determinó que los desvíos `S4` y `S9` deben permanecer desactivados
   en la configuración ganadora.
3. **Tratamiento de Piraeus.** Durante el cierre, `S7` omite Piraeus mediante
   un ciclo conectado y más corto. El bypass de `S1` existe como experimento,
   pero está desactivado en la configuración validada porque su recorrido es
   considerablemente mayor.
4. **Prioridad de atraque.** Ordena los buques usando los TEU-hora acumulados
   por la carga y el tiempo esperando atraque, evitando dejar indefinidamente
   un buque en cola.

El `Loss` se acumula por intervalos de cinco días al comparar el Average
Transport Time (ATT) del escenario base contra el ATT con disrupciones. Por
eso, además de los retrasos directos, afectan especialmente el resultado la
carga sin completar, las esperas en origen, los transbordos y los buques que
inician un tramo mientras su multiplicador está activo.

## Optimización indefinida con Optuna

El optimizador está completamente separado de la estrategia operativa en
`response_strategies/optimize_round2.py`. Cada ensayo crea el escenario con
disrupciones, usa la semilla determinista `2026`, ejecuta los 140 días de
*warm-up* y calcula el `Loss` sobre los 360 días de medición con la misma
precisión del dashboard.

### Preparación

Todos los comandos deben ejecutarse desde la raíz del proyecto y dentro del
entorno virtual. Optuna se instala una sola vez:

```bash
source .venv/bin/activate
python -m pip install optuna
```

También es posible utilizar directamente el intérprete del entorno sin
activarlo:

```bash
.venv/bin/python -m pip install optuna
```

### Dejar la búsqueda corriendo indefinidamente

La forma recomendada es iniciar el proceso desacoplado:

```bash
.venv/bin/python response_strategies/optimize_round2.py --daemon
```

El proceso continúa ejecutando ensayos hasta que se detenga explícitamente.
Si se vuelve a ejecutar el comando mientras ya existe un optimizador activo,
no inicia un trabajador duplicado.

Consultar el estado y el mejor resultado encontrado:

```bash
.venv/bin/python response_strategies/optimize_round2.py --status
```

Detener el proceso:

```bash
.venv/bin/python response_strategies/optimize_round2.py --stop
```

Ejecutarlo en primer plano, por ejemplo para observar directamente la salida:

```bash
.venv/bin/python response_strategies/optimize_round2.py --worker
```

Para limitar una ejecución a una cantidad concreta de ensayos:

```bash
.venv/bin/python response_strategies/optimize_round2.py --worker --trials 10
```

Ejecutar nuevamente la mejor combinación guardada, escribir sus resultados en
`Output/`, crear el log normal en `Logs/` y abrir el dashboard al finalizar:

```bash
.venv/bin/python response_strategies/optimize_round2.py --run-best
```

Ejecutar una combinación específica usando su número de ensayo:

```bash
.venv/bin/python response_strategies/optimize_round2.py --run-trial 15
```

Ambos comandos reutilizan `main.py` y, por lo tanto, tardan lo mismo que una
simulación completa. Los CSV existentes en `Output/` son reemplazados por los
de la combinación seleccionada. El estudio SQLite y la ejecución indefinida de
Optuna no se eliminan ni se reinician.

### Persistencia y archivos de resultados

Optuna analiza doce decisiones: espera estimada de embarque, duración de
escala, anticipación de los tres desvíos, anticipación de `S7` y `S1`, peso de
espera para atraque y activación de las alternativas `S4`, `S9`, `S7` y `S1`.
El desvío `S5` se conserva siempre porque evita el retraso conocido más
costoso del escenario.

Los archivos generados se guardan en `response_strategies/optuna_state/`:

* `round2.db`: estudio SQLite con todos los ensayos.
* `best.json`: menor `Loss`, parámetros y variables de entorno correspondientes.
* `optimizer.log`: progreso y errores del proceso en segundo plano.
* `optimizer.pid`: identificador del proceso activo.

La carpeta está ignorada por Git. Si una ejecución se interrumpe, el siguiente
inicio reutiliza la misma base de datos, marca el ensayo incompleto y vuelve a
poner esa combinación en la cola. Las combinaciones claramente malas pueden
podarse antes de completar los 360 días, reduciendo el tiempo desperdiciado.

### Cómo busca las combinaciones

La búsqueda no incrementa las variables paso a paso. Utiliza el sampler TPE
(*Tree-structured Parzen Estimator*) de Optuna con semilla `2026` y modo
multivariable:

1. El estudio comienza con la combinación ya validada de `Loss 3.295500` y
   una prueba estructural de bypass de `S1` puesta en cola.
2. Hasta reunir suficientes observaciones, explora valores distribuidos por
   los rangos configurados. Las variables continuas pueden tomar cualquier
   valor dentro de su intervalo y las categóricas activan o desactivan una
   estrategia.
3. Después de la fase inicial, TPE separa estadísticamente las combinaciones
   buenas de las restantes y propone candidatos que tengan mayor probabilidad
   de pertenecer al grupo de menor `Loss`. El modo multivariable también
   considera interacciones entre parámetros.
4. Cada cinco días simulados se reporta el `Loss` parcial. Cuando existen al
   menos diez ensayos completos y se han medido al menos 24 intervalos, el
   `MedianPruner` puede detener una combinación cuyo resultado parcial sea peor
   que la mediana de ensayos comparables.

El algoritmo combina exploración y explotación: con el tiempo concentra más
propuestas cerca de regiones prometedoras, pero sigue generando variación. No
existe actualmente una regla especial de estancamiento que obligue a probar
automáticamente los extremos; un extremo se selecciona si el modelo
probabilístico lo considera prometedor o durante la exploración inicial. Si la
búsqueda converge durante muchos ensayos, se pueden ampliar los rangos o
poner combinaciones extremas específicas en cola.

---

## Pruebas Unitarias

Para validar el correcto funcionamiento de las utilidades de simulación (`o2despy`), puedes ejecutar las pruebas mediante `pytest`:

```bash
pytest
```
