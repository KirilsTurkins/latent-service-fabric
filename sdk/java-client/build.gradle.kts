import org.gradle.util.GradleVersion

plugins {
    `java-library`
}

require(GradleVersion.current() >= GradleVersion.version("9.1.0")) {
    "Java 25 requires Gradle 9.1.0 or newer; see docs/development/toolchain.md"
}

group = "dev.latent"
version = "0.1.0-alpha.3"

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(25))
        vendor.set(JvmVendorSpec.ADOPTIUM)
    }
}

repositories {
    mavenCentral()
}

val sdkLauncher = javaToolchains.launcherFor {
    languageVersion.set(JavaLanguageVersion.of(25))
    vendor.set(JvmVendorSpec.ADOPTIUM)
}

val verifyJavaToolchain by tasks.registering(Exec::class) {
    workingDir(rootDir.parentFile.parentFile)
    doFirst {
        commandLine("python3", "sdk/java-client/tools/java_toolchain.py", "check",
            "--java-home", sdkLauncher.get().metadata.installationPath.asFile.absolutePath)
    }
}

val prepareTransport by tasks.registering(Exec::class) {
    dependsOn(verifyJavaToolchain)
    workingDir(rootDir.parentFile.parentFile)
    commandLine("python3", "sdk/java-client/tools/build.py", "prepare")
}

sourceSets {
    main {
        java.srcDirs("src/transport/java", "src/example/java", "build/generated/java")
    }
    test {
        java.srcDir("src/transportTest/java")
    }
}

val dependencyLock = groovy.json.JsonSlurper().parse(file("dependencies.lock.json")) as Map<*, *>
val lockedArtifacts = (dependencyLock["artifacts"] as List<*>).map { it as Map<*, *> }
val dependencyFiles = lockedArtifacts.filter { it["platform"] == "any" }
    .map { file("build/deps/" + (it["path"] as String).substringAfterLast('/')) }

dependencies { api(files(dependencyFiles)) }

tasks.compileJava { dependsOn(prepareTransport); options.release.set(25) }
tasks.compileTestJava { options.release.set(25) }

tasks.withType<JavaExec>().configureEach {
    javaLauncher.set(sdkLauncher)
}

val semanticTest by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.latent.sdk.InvocationIdentityTest")
}

val transportTest by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    workingDir(rootDir.parentFile.parentFile)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.latent.sdk.transport.TransportTest")
    enableAssertions = true
}

// These maintained suites are executable main classes, not JUnit tests.
// Keep `test` useful and fail on either suite's exit status; only empty JUnit
// discovery is expected, and must not replace or skip the real SDK suites.
tasks.test {
    dependsOn(semanticTest, transportTest)
    failOnNoDiscoveredTests.set(false)
}

val verifyJavaBytecode by tasks.registering(Exec::class) {
    dependsOn(tasks.testClasses, tasks.jar)
    workingDir(rootDir.parentFile.parentFile)
    doFirst {
        commandLine("python3", "sdk/java-client/tools/java_toolchain.py", "classes",
            layout.buildDirectory.dir("classes/java/main").get().asFile.absolutePath,
            layout.buildDirectory.dir("classes/java/test").get().asFile.absolutePath,
            tasks.jar.get().archiveFile.get().asFile.absolutePath)
    }
}

tasks.check { dependsOn(semanticTest, transportTest, verifyJavaBytecode) }
