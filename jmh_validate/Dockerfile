# LockSense Job 2 — JMH Contention Validator
# ============================================
# Builds the JMH fat JAR inside the image and provides an entrypoint to run
# the benchmarks.  Output is written to /output (mount a host directory there).
#
# Build (from Locksense/ root):
#   docker build -t locksense-job2 -f job2_validate/Dockerfile job2_validate/
#
# Run (results land in the current directory on the host):
#   docker run --rm -v "%cd%":/output locksense-job2
#
# JMH flags can be appended after the image name:
#   docker run --rm -v "%cd%":/output locksense-job2 -wi 3 -i 5

# ── Stage 1: Maven build ──────────────────────────────────────────────────────
FROM maven:3.9-eclipse-temurin-17 AS builder

WORKDIR /build
COPY pom.xml ./
COPY src     ./src

# Download dependencies first (layer-cached separately from source)
RUN mvn -q dependency:go-offline -DskipTests
RUN mvn -q package -DskipTests

# ── Stage 2: Minimal JRE runtime ─────────────────────────────────────────────
FROM eclipse-temurin:17-jdk-jammy

WORKDIR /app
COPY --from=builder /build/target/benchmarks.jar ./benchmarks.jar

# Fixed heap: reduces GC variance so throughput differences reflect lock overhead
ENV JAVA_OPTS="-Xms512m -Xmx2g -XX:+UseG1GC"

# Default JMH invocation writes JSON results to /output/jmh_raw.json.
# Override any option by appending arguments after the image name.
ENTRYPOINT ["sh", "-c", \
  "java $JAVA_OPTS -jar /app/benchmarks.jar \
   -rf json -rff /output/jmh_raw.json \
   -wi ${WI:-5} -i ${MI:-10} -f ${FORKS:-1} \
   $@", "--"]
