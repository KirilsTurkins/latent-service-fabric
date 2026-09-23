plugins { java }

repositories { mavenCentral() }

java { toolchain { languageVersion.set(JavaLanguageVersion.of(25)) } }
tasks.withType<JavaCompile>().configureEach { options.release.set(25) }

layout.buildDirectory.set(file(providers.gradleProperty("lsfOutput").get()))
dependencyLocking { lockAllConfigurations() }

dependencies {
    implementation("org.teavm:teavm-tooling:0.15.0")
    implementation("org.teavm:teavm-classlib:0.15.0")
    implementation("org.teavm:teavm-interop:0.15.0")
    implementation("org.teavm:teavm-jso:0.15.0")
}

for ((taskName, backend) in listOf("compileC" to "C", "compileGC" to "WEBASSEMBLY_GC")) {
    tasks.register<JavaExec>(taskName) {
        dependsOn(tasks.classes)
        classpath = sourceSets.main.get().runtimeClasspath
        mainClass.set("dev.latent.probe.Compile")
        args(backend, layout.buildDirectory.dir(backend).get().asFile.absolutePath)
        maxHeapSize = "1g"
    }
}

tasks.register<JavaExec>("checkSourceSemantics") {
    dependsOn(tasks.classes)
    classpath = sourceSets.main.get().runtimeClasspath
    mainClass.set("dev.latent.probe.Probe")
}
