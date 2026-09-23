import java.security.MessageDigest

plugins { java }

repositories { mavenCentral() }

// The probe records the resolved graph; this is not yet a verified SDK lockfile.
val teavmVersion = "0.15.0"
dependencies {
    implementation("org.teavm:teavm-tooling:$teavmVersion")
    runtimeOnly("org.teavm:teavm-classlib:$teavmVersion")
}

val probeOutput = providers.gradleProperty("lsfProbeOutput")
layout.buildDirectory.set(file(probeOutput.get()).resolve("gradle-build"))

tasks.withType<JavaCompile>().configureEach {
    options.release.set(25)
    options.encoding = "UTF-8"
}

// Explicit opt-in output, no wrapper download or toolchain auto-provisioning.
tasks.register("prepareProbe") {
    dependsOn(tasks.classes)
    doLast {
        val destination = file(probeOutput.get())
        destination.resolve("classpath.txt").writeText(sourceSets.main.get().runtimeClasspath.asPath)
        val records = configurations.runtimeClasspath.get().resolvedConfiguration.resolvedArtifacts
            .sortedBy { it.moduleVersion.id.toString() + ":" + it.name }
            .map {
                val sha256 = MessageDigest.getInstance("SHA-256")
                it.file.inputStream().use { input ->
                    val buffer = ByteArray(65536)
                    while (true) {
                        val count = input.read(buffer)
                        if (count == -1) break
                        sha256.update(buffer, 0, count)
                    }
                }
                val digest = sha256.digest().joinToString("") { byte -> "%02x".format(byte.toInt() and 255) }
                "${it.moduleVersion.id}\t${it.file.name}\t${it.file.length()}\t$digest"
            }
        destination.resolve("resolved-artifacts.tsv").writeText(records.joinToString("\n", postfix = "\n"))
    }
}
